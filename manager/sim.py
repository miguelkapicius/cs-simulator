"""Simulação de fumaça do manager: roda temporadas sem jogador ativo e resume a economia.

Uso: .venv/bin/python -m manager.sim --seed 1 --seasons 3
"""
import argparse
from typing import List

from manager.game import advance_week, new_game
from manager.params import load_params


def run(seed: int, seasons: int, difficulty: str = "normal") -> List[str]:
    weeks = load_params()["season_weeks"]
    world = new_game(seed, difficulty, "Clube do Jogador")
    lines = []
    for season in range(1, seasons + 1):
        prices = []
        for _ in range(weeks):
            prices += [e.data["price"] for e in advance_week(world) if e.kind == "signed" and e.data["price"]]
        human = world.clubs[world.human_cid]
        broke = sum(1 for c in world.clubs.values() if not c.is_human and c.budget == 0)
        top = ", ".join("$%s" % format(x, ",") for x in sorted(prices, reverse=True)[:3]) or "nenhuma"
        lines.append("Temporada %d: clube do jogador no Tier %d, caixa $%s, %d jogadores" %
                     (season, human.tier, format(human.budget, ","), len(human.roster)))
        lines.append("  transferências com buyout: %d, maiores: %s" % (len(prices), top))
        lines.append("  clubes do computador com caixa zerado: %d" % broke)
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--seasons", type=int, default=3)
    ap.add_argument("--difficulty", default="normal")
    args = ap.parse_args()
    print("\n".join(run(args.seed, args.seasons, args.difficulty)))


if __name__ == "__main__":
    main()
