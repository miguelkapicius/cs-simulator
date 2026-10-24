"""Valida o contrato inteiro: artefatos x schemas, vetores de teste x referência e log de exemplo.

Uso: .venv/bin/python -m pipeline.validate_contract
Sai com código 1 se algo estiver fora do contrato.
"""
import json
import re
import sys

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from calibration.validate_log import validate_file
from contract.reference import team_model as ref
from contract.reference import manifest as man
from contract.reference import tactics as tac
from contract.reference import weapon_dynamics as wd
from pipeline.common import ARTIFACTS_DIR, CONTRACT_DIR, CONTRACT_VERSION, EXAMPLES_DIR, SCHEMAS_DIR, VECTORS_DIR

ARTIFACT_SCHEMAS = {
    "player_profiles.json": "player_profiles.schema.json",
    "game_rules.json": "game_rules.schema.json",
    "team_model.json": "team_model.schema.json",
    "calibration_targets.json": "calibration_targets.schema.json",
    "weapon_dynamics.json": "weapon_dynamics.schema.json",
    "tactics.json": "tactics.schema.json",
    "tactics_playbook.json": "tactics_playbook.schema.json",
    "elite_players.json": "elite_players.schema.json",
}
MAX_ERRORS = 8


def registry():
    resources = []
    for f in SCHEMAS_DIR.glob("*.json"):
        doc = json.loads(f.read_text())
        resource = Resource.from_contents(doc)
        resources += [(f.name, resource), (doc["$id"], resource)]
    return Registry().with_resources(resources)


def check_artifacts(reg):
    problems = []
    for artifact, schema_name in ARTIFACT_SCHEMAS.items():
        path = ARTIFACTS_DIR / artifact
        if not path.exists():
            problems.append(f"{artifact}: arquivo não encontrado (rode o pipeline)")
            continue
        doc = json.loads(path.read_text())
        errors = sorted(Draft202012Validator(json.loads((SCHEMAS_DIR / schema_name).read_text()), registry=reg).iter_errors(doc),
                        key=lambda e: list(e.path))
        for e in errors[:MAX_ERRORS]:
            problems.append(f"{artifact}: {'.'.join(str(p) for p in e.path) or '(raiz)'}: {e.message[:150]}")
        if len(errors) > MAX_ERRORS:
            problems.append(f"{artifact}: ... e mais {len(errors) - MAX_ERRORS} erros")
        v, cur = [int(x) for x in doc.get("contract_version", "0.0.0").split(".")], [int(x) for x in CONTRACT_VERSION.split(".")]
        if v[0] != cur[0] or v > cur:   # MINOR/PATCH mais antigos continuam válidos: o contrato só acrescentou
            problems.append(f"{artifact}: contract_version {doc.get('contract_version')} incompatível com {CONTRACT_VERSION} (regenere o artefato)")
    return problems


def check_vectors():
    path = VECTORS_DIR / "team_model_vectors.json"
    model_path = ARTIFACTS_DIR / "team_model.json"
    if not path.exists() or not model_path.exists():
        return ["team_model_vectors.json ou team_model.json ausente"]
    model, vec = json.loads(model_path.read_text()), json.loads(path.read_text())
    tol, problems = vec["tolerance"], []
    for i, case in enumerate(vec["win_probability"]):
        got = ref.win_probability(model, case["input"])
        if abs(got - case["expected"]) > tol:
            problems.append(f"win_probability[{i}]: esperado {case['expected']}, obtido {got}")
    for name, fn in (("buy_distribution", ref.buy_distribution), ("round_plan", ref.round_plan)):
        for i, case in enumerate(vec[name]):
            got = fn(model, case["input"])
            if json.dumps(got, sort_keys=True) != json.dumps(case["expected"], sort_keys=True):
                problems.append(f"{name}[{i}]: esperado {case['expected']}, obtido {got}")
    for i, case in enumerate(vec["buy_distribution"]):
        total = sum(case["expected"].values())
        if abs(total - 1) > 1e-3:
            problems.append(f"buy_distribution[{i}]: probabilidades somam {total}")
    return problems


def check_weapon_vectors():
    path, model_path = VECTORS_DIR / "weapon_dynamics_vectors.json", ARTIFACTS_DIR / "weapon_dynamics.json"
    if not path.exists() or not model_path.exists():
        return ["weapon_dynamics_vectors.json ou weapon_dynamics.json ausente"]
    model, vec = json.loads(model_path.read_text()), json.loads(path.read_text())
    tol, problems = vec["tolerance"], []
    for name, fn in (("next_bullet_index", lambda i: wd.next_bullet_index(model, i["weapon"], i["prev_index"], i["pause_s"])),
                     ("punch", lambda i: list(wd.punch(model, i["weapon"], i["bullet"]))),
                     ("accuracy_penalty", lambda i: wd.accuracy_penalty(model, i["weapon"], i["bullet"])),
                     ("bullet_direction", lambda i: list(wd.bullet_direction(model, i["weapon"], i["eye_pitch"], i["eye_yaw"], i["bullet"])))):
        for k, case in enumerate(vec[name]):
            got, exp = fn(case["input"]), case["expected"]
            gl, el = (got if isinstance(got, list) else [got]), (exp if isinstance(exp, list) else [exp])
            if len(gl) != len(el) or any(abs(a - b) > tol for a, b in zip(gl, el)):
                problems.append(f"{name}[{k}]: esperado {exp}, obtido {got}")
    return problems


def check_tactics_vectors():
    vec_path = VECTORS_DIR / "tactics_vectors.json"
    paths = (vec_path, ARTIFACTS_DIR / "tactics.json", ARTIFACTS_DIR / "tactics_playbook.json")
    if not all(p.exists() for p in paths):
        return ["tactics_vectors.json, tactics.json ou tactics_playbook.json ausente"]
    vec, model, playbook = (json.loads(p.read_text()) for p in paths)
    by_id = {mp: {r["id"]: r for r in m["rounds"]} for mp, m in playbook["maps"].items()}
    tol, problems = vec["tolerance"], []

    def same(a, b):
        if isinstance(a, dict) and isinstance(b, dict):
            return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
        if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
            return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
            return abs(a - b) <= tol
        return a == b

    fns = {
        "zone": lambda i: tac.zone(model, i["map"], i["place"]),
        "next_places": lambda i: tac.next_places(model, i["map"], i["place"]),
        "occupancy": lambda i: tac.occupancy(model, i["map"], i["side"], i["t"]),
        "forecast": lambda i: tac.forecast(model, i["map"], i["side"], i["place"], i["horizon_s"]),
        "rotation": lambda i: tac.rotation(model, i["map"], i["contact_zone"], i["own_zone"]),
        "round_weights": lambda i: (lambda w: {"n": len(w), "weight": w[0][1], "first_ids": [x[0] for x in w[:3]]})(tac.round_weights(playbook, i["map"], i["t_buy"])),
        "place_at": lambda i: tac.place_at(by_id[i["map"]][i["round_id"]], i["side"], i["player_index"], i["t"]),
        "plant_site": lambda i: tac.plant_site_probability(model, i["map"], i["t"], i["t_a"], i["t_b"], i["ct_a"], i["ct_b"]),
        "site_switch": lambda i: tac.site_switch_probability(model, i["map"], i["t_here"], i["ct_here"], i["t_other"], i["ct_other"]),
    }
    for name, fn in fns.items():
        for k, case in enumerate(vec[name]):
            got = fn(case["input"])
            if not same(got, case["expected"]):
                problems.append(f"{name}[{k}]: esperado {case['expected']}, obtido {got}")
    return problems


SHARDED = CONTRACT_DIR / "sharded"
HEADER = ("schema_version", "contract_version", "generated_at")


def _strip(d, *extra):
    return {k: v for k, v in d.items() if k not in HEADER and k not in extra}


def check_shards(reg):
    """Manifesto válido, arquivos com o tamanho e o hash declarados, e as fatias remontam exatamente os arquivos únicos."""
    path = SHARDED / "manifest.json"
    if not path.exists():
        return ["sharded/manifest.json ausente (rode: make shards)"]
    manifest = json.loads(path.read_text())
    problems = []
    schema = json.loads((SCHEMAS_DIR / "manifest.schema.json").read_text())
    for e in sorted(Draft202012Validator(schema, registry=reg).iter_errors(manifest), key=lambda x: list(x.path))[:MAX_ERRORS]:
        problems.append(f"manifest: {'.'.join(str(p) for p in e.path) or '(raiz)'}: {e.message[:150]}")
    if problems:
        return problems
    if manifest["contract_version"].split(".")[0] != CONTRACT_VERSION.split(".")[0]:
        problems.append(f"manifest: contract_version {manifest['contract_version']} incompatível com {CONTRACT_VERSION}")

    import hashlib
    for entry in man.all_files(manifest):
        f = CONTRACT_DIR / entry["path"]
        if not f.exists():
            problems.append(f"{entry['path']}: arquivo ausente")
            continue
        data = f.read_bytes()
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            problems.append(f"{entry['path']}: tamanho ou sha256 diferente do manifesto (rode: make shards)")
    if problems:
        return problems

    load = lambda rel: json.loads((CONTRACT_DIR / rel).read_text())
    profiles, tactics, playbook = (json.loads((ARTIFACTS_DIR / n).read_text()) for n in ("player_profiles.json", "tactics.json", "tactics_playbook.json"))

    base = load(manifest["global"]["profiles_baseline"]["path"])
    players = [load(e["path"]) for e in sorted(manifest["players"].values(), key=lambda e: e["index"])]
    if {**_strip(base), "players": [_strip(p) for p in players]} != _strip(profiles):
        problems.append("as fatias de jogadores + baseline não remontam player_profiles.json")
    glob_t = load(manifest["global"]["tactics_global"]["path"])
    maps_t = {mp: _strip(load(m["tactics"]["path"]), "map") for mp, m in manifest["maps"].items()}
    if {**_strip(glob_t), "maps": maps_t} != _strip(tactics):
        problems.append("as fatias de tática + dados globais não remontam tactics.json")
    maps_p = {mp: _strip(load(m["playbook"]["path"]), "map") for mp, m in manifest["maps"].items()}
    if maps_p != playbook["maps"]:
        problems.append("as fatias de playbook não remontam tactics_playbook.json")

    # cada jogador pertence a exatamente um time, e o time lista só jogadores existentes
    seen = [p for t in manifest["teams"].values() for p in t["players"]]
    if sorted(seen) != sorted(manifest["players"]) or len(seen) != len(set(seen)):
        problems.append("os elencos dos times não cobrem cada jogador exatamente uma vez")
    for team, t in manifest["teams"].items():
        if any(manifest["players"][p]["team"] != team for p in t["players"]):
            problems.append(f"time {team}: jogador com time diferente no manifesto")

    vec_path = VECTORS_DIR / "manifest_vectors.json"
    if not vec_path.exists():
        problems.append("manifest_vectors.json ausente")
    else:
        for i, case in enumerate(json.loads(vec_path.read_text())["cases"]):
            got = man.match_files(manifest, case["input"]["map"], case["input"]["team_a"], case["input"]["team_b"])
            exp = case["expected"]
            if len(got["files"]) != exp["n_files"] or got["bytes"] != exp["bytes"] or ("files" in exp and got["files"] != exp["files"]):
                problems.append(f"manifest_vectors[{i}]: esperado {exp['n_files']} arquivos / {exp['bytes']} bytes, obtido {len(got['files'])} / {got['bytes']}")
    return problems


def check_elite_identity(doc=None):
    """elite_players.json não pode carregar nome, steamid nem time reais, nem em texto solto."""
    if doc is None:
        path = ARTIFACTS_DIR / "elite_players.json"
        if not path.exists():
            return ["elite_players.json ausente (rode make elite)"]
        doc = json.loads(path.read_text())
    real = json.loads((ARTIFACTS_DIR / "player_profiles.json").read_text())["players"]
    dump = json.dumps(doc, ensure_ascii=False)
    problems = []
    idents = {x for p in real for x in (p["name"], p["steamid"], p["team"])}
    for ident in sorted(idents):
        if f'"{ident}"' in dump or any(c["codename"].lower() == ident.lower() for c in doc["players"]):
            problems.append(f"elite_players.json contém a identidade real {ident!r}")
    if re.search(r"\d{17}", dump):
        problems.append("elite_players.json contém um número de 17 dígitos (parece steamid)")
    return problems


def check_example():
    path = EXAMPLES_DIR / "sim_log_example.jsonl"
    if not path.exists():
        return ["examples/sim_log_example.jsonl ausente"]
    errors, _ = validate_file(path)
    return [f"sim_log_example.jsonl: {e}" for e in errors]


def main():
    reg = registry()
    for f in sorted(SCHEMAS_DIR.glob("*.json")):
        Draft202012Validator.check_schema(json.loads(f.read_text()))
    sections = {"artefatos x schemas": check_artifacts(reg), "vetores do modelo de time x referência": check_vectors(),
                "vetores de recuo x referência": check_weapon_vectors(),
                "vetores da camada tática x referência": check_tactics_vectors(),
                "fatias independentes (manifesto, hashes, remontagem)": check_shards(reg),
                "elite_players sem identidade real": check_elite_identity(),
                "log de exemplo": check_example()}
    bad = 0
    print(f"Contrato {CONTRACT_VERSION} ({CONTRACT_DIR.name}/)")
    for name, problems in sections.items():
        print(f"  {'OK  ' if not problems else 'ERRO'} {name}")
        for p in problems:
            print("       -", p)
        bad += len(problems)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
