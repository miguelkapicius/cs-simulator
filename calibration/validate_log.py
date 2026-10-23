"""Valida um log da simulação (.jsonl) contra o contrato.

Duas camadas: (1) cada linha contra contract/schemas/sim_log.schema.json; (2) coerência entre eventos
(rounds em sequência, jogadores conhecidos, ticks crescentes, armas existentes em game_rules.json...).

Uso: .venv/bin/python -m calibration.validate_log caminho/log.jsonl [...]
Código de saída: 0 = válido (pode ter avisos), 1 = tem erros.
"""
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from pipeline.common import ARTIFACTS_DIR, CONTRACT_VERSION, SCHEMAS_DIR

MAX_REPORTED = 20
SPECIAL_WEAPONS = {"world", "planted_c4", "inferno", "hegrenade", "molotov", "incgrenade", "taser", "knife", "c4"}


def _known_weapons():
    path = ARTIFACTS_DIR / "game_rules.json"
    if not path.exists():
        return None
    return set(json.loads(path.read_text())["weapons"]) | SPECIAL_WEAPONS


def validate_file(path):
    """Retorna (erros, avisos), listas de strings."""
    schema = json.loads((SCHEMAS_DIR / "sim_log.schema.json").read_text())
    defs = schema["$defs"]
    validators = {name: Draft202012Validator({"$schema": schema["$schema"], "$defs": defs, **defs[name]})
                  for name in ("match_start", "round_start", "freeze_end", "shot", "damage", "kill", "bomb",
                               "grenade", "sighting", "round_end", "match_end")}
    weapons = _known_weapons()
    errors, warnings = [], []

    def err(msg):
        errors.append(msg)

    players, match_start, last_tick = set(), None, -1
    current_round, state, seen_rounds = 0, None, []
    unknown_weapons = {}
    n_events = 0

    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            n_events += 1
            try:
                e = json.loads(line)
            except json.JSONDecodeError as ex:
                err(f"linha {n}: JSON inválido ({ex.msg})")
                continue
            t = e.get("type")
            if t not in validators:
                err(f"linha {n}: type desconhecido {t!r}")
                continue
            problems = sorted(validators[t].iter_errors(e), key=lambda x: list(x.path))
            for p in problems[:3]:
                where = ".".join(str(x) for x in p.path) or "(raiz)"
                err(f"linha {n} [{t}]: {where}: {p.message[:140]}")
            if problems:
                continue

            if t == "match_start":
                if match_start:
                    err(f"linha {n}: match_start repetido")
                match_start = e
                players = {p["player"] for p in e["players"]}
                log_v, cur_v = [int(x) for x in e["contract_version"].split(".")], [int(x) for x in CONTRACT_VERSION.split(".")]
                if log_v[0] != cur_v[0]:
                    err(f"contract_version {e['contract_version']} incompatível com o contrato atual {CONTRACT_VERSION} (MAJOR diferente)")
                elif log_v > cur_v:
                    warnings.append(f"contract_version {e['contract_version']} é mais novo que o contrato atual {CONTRACT_VERSION}")
                continue
            if not match_start:
                err(f"linha {n}: evento {t} antes de match_start")
                return errors, warnings
            if t == "match_end":
                continue

            if e["tick"] < last_tick:
                err(f"linha {n} [{t}]: tick {e['tick']} menor que o evento anterior ({last_tick})")
            last_tick = max(last_tick, e["tick"])

            if t == "round_start":
                if e["round"] != current_round + 1:
                    err(f"linha {n}: round_start {e['round']} depois do round {current_round} (esperado {current_round + 1})")
                if state not in (None, "ended"):
                    err(f"linha {n}: round_start {e['round']} sem round_end do round anterior")
                current_round, state = e["round"], "started"
                seen_rounds.append(e["round"])
                continue
            if e["round"] != current_round or state is None:
                err(f"linha {n} [{t}]: round {e['round']} fora do round em andamento ({current_round})")
                continue
            if t == "freeze_end":
                if state != "started":
                    err(f"linha {n}: freeze_end duplicado no round {current_round}")
                state = "playing"
                if len(e["players"]) != 10:
                    warnings.append(f"round {current_round}: freeze_end com {len(e['players'])} jogadores (esperado 10)")
                for p in e["players"]:
                    if p["player"] not in players:
                        err(f"linha {n}: jogador {p['player']} não está em match_start.players")
                continue
            if t == "round_end":
                if state != "playing":
                    err(f"linha {n}: round_end do round {current_round} sem freeze_end")
                state = "ended"
                continue
            # Depois do round_end são esperados exit frags e dano pós-round (o carregador os marca como after_round_end)
            if state == "started" and t in ("shot", "damage", "kill", "sighting"):
                warnings.append(f"linha {n} [{t}]: evento durante o freeze time do round {current_round}")

            for field in ("shooter", "attacker", "victim", "assister", "observer", "target", "thrower", "player"):
                v = e.get(field)
                if v is not None and v not in players:
                    err(f"linha {n} [{t}]: {field}={v} não está em match_start.players")
            w = e.get("weapon")
            if weapons is not None and w and w not in weapons and not w.startswith("knife"):
                unknown_weapons[w] = unknown_weapons.get(w, 0) + 1

    if not match_start:
        err("arquivo sem match_start")
    if state not in ("ended", None):
        err(f"último round ({current_round}) sem round_end")
    if n_events and not seen_rounds:
        err("nenhum round_start")
    if unknown_weapons:
        warnings.append("armas que não existem em game_rules.json: " + ", ".join(f"{k} ({v}x)" for k, v in sorted(unknown_weapons.items())))
    return errors, warnings


def main(argv):
    paths = [Path(a) for a in argv] or []
    if not paths:
        print(__doc__)
        return 2
    code = 0
    for path in paths:
        errors, warnings = validate_file(path)
        status = "VÁLIDO" if not errors else "INVÁLIDO"
        print(f"{path}: {status} ({len(errors)} erros, {len(warnings)} avisos)")
        for m in errors[:MAX_REPORTED]:
            print("  ERRO ", m)
        if len(errors) > MAX_REPORTED:
            print(f"  ... e mais {len(errors) - MAX_REPORTED} erros")
        for m in warnings[:MAX_REPORTED]:
            print("  aviso", m)
        code = code or (1 if errors else 0)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
