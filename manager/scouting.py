"""Scouting: o manager nunca vê o nível real, só uma estimativa que melhora com o nível de observação."""
import hashlib
import random
from typing import Dict

from manager.models import Player
from manager.params import load_params


def _noise(world_seed: int, pid: str, level: int, key: str, width: float) -> float:
    """Ruído uniforme em [-width, width], fixo para (mundo, jogador, nível, atributo): ver de novo não sorteia de novo."""
    digest = hashlib.sha256(("%s:%s:%s:%s" % (world_seed, pid, level, key)).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big")).uniform(-width, width)


def _clamp(x: float) -> float:
    return max(0.0, min(100.0, x))


def scout_view(player: Player, level: int, world_seed: int) -> Dict:
    prm = load_params()["scouting"]
    width = prm["noise"][str(level)]
    view = {
        "pid": player.pid, "codename": player.codename, "country": player.country, "role": player.role,
        "age": player.age, "hype": player.hype, "form": player.form,
        "skill_estimate": round(_clamp(player.skill + _noise(world_seed, player.pid, level, "skill", width)), 1),
    }
    for key in prm["reveals"].get(str(level), []):
        view[key] = round(_clamp(player.hidden[key] + _noise(world_seed, player.pid, level, key, width)), 1)
    return view


def scout_cost(level: int, prm: Dict) -> Dict:
    return dict(prm["scouting"]["cost"][str(level)])
