"""Gera contract/artifacts/elite_players.json: os 40 jogadores de comportamento real, com identidade ficcional.

O comportamento (mecânica, desempenho, armas, posições) é o dos perfis medidos nas demos. O que identifica
alguém (nome, steamid, time e o bloco `source`, que cita times e demos) nunca entra. Codinome, país e idade
são sorteados com semente fixa, então o arquivo é reproduzível. É este arquivo, e não player_profiles.json,
que um produto deve usar para mostrar jogadores.

Uso: .venv/bin/python -m pipeline.build_elite_players
"""
import json
from datetime import date

from manager.elite import elite_players
from pipeline.common import ARTIFACTS_DIR, CONTRACT_VERSION

ELITE_SEED = 2026
BEHAVIOR_KEYS = ("role_tags", "mechanics", "performance", "weapons", "positions")
PLAYER_KEYS = ("pid", "codename", "country", "role", "age", "tier", "skill", "hidden", "hype", "form")


def build() -> dict:
    with open(ARTIFACTS_DIR / "player_profiles.json", encoding="utf-8") as f:
        profiles = json.load(f)["players"]
    players = []
    for p in elite_players(ELITE_SEED):
        real = profiles[int(p.profile_ref)]
        entry = {k: getattr(p, k) for k in PLAYER_KEYS}
        entry["profile"] = {k: real[k] for k in BEHAVIOR_KEYS}
        players.append(entry)
    return {
        "schema_version": "1.0", "contract_version": CONTRACT_VERSION, "generated_at": date.today().isoformat(),
        "seed": ELITE_SEED, "players": players,
    }


def main() -> None:
    doc = build()
    out = ARTIFACTS_DIR / "elite_players.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print("%s: %d jogadores, %.0f KB" % (out.name, len(doc["players"]), out.stat().st_size / 1024))


if __name__ == "__main__":
    main()
