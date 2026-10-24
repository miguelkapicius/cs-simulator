"""Scouting: o manager nunca vê o nível real, só uma estimativa que melhora com o nível de observação."""
from typing import Dict

from contract.reference import manager_economy as eco
from manager.models import Player
from manager.params import load_params


def scout_view(player: Player, level: int, world_seed: int) -> Dict:
    numbers = eco.scout_numbers(player.skill, player.hidden, player.pid, level, world_seed, load_params())
    view = {"pid": player.pid, "codename": player.codename, "country": player.country, "role": player.role,
            "age": player.age, "hype": player.hype, "form": player.form}
    view.update({k: round(v, 1) for k, v in numbers.items()})
    return view


def scout_cost(level: int, prm: Dict) -> Dict:
    return dict(prm["scouting"]["cost"][str(level)])
