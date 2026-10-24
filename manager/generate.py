"""Gerador de jogadores fictícios por tier: mesmas regras de comportamento, atributos piores nos tiers baixos."""
import random
from typing import Optional, Set

from manager.identity import make_codename, make_country
from manager.models import HIDDEN_KEYS, Player
from manager.params import load_params


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def generate_player(rng: random.Random, tier: int, taken: Set[str], role: Optional[str] = None) -> Player:
    g = load_params()["generator"]
    t = str(tier)
    if role is None:
        roles, weights = zip(*sorted(g["role_weights"].items()))
        role = rng.choices(roles, weights=weights)[0]
    skill = _clamp(rng.gauss(g["skill_mean"][t], g["skill_std"]))
    hidden = {k: _clamp(rng.gauss(g["hidden_mean"][t], 8)) for k in HIDDEN_KEYS}
    if rng.random() < g["tail_prob"][t]:
        # talento jovem escondido: ainda fraco hoje, teto alto
        age = rng.randint(17, 20)
        hidden["ceiling"] = rng.uniform(85, 98)
        skill = _clamp(skill - 5)
    else:
        age = rng.randint(18, 34)
        hidden["ceiling"] = min(84.0, hidden["ceiling"])
    codename = make_codename(rng, taken)  # único no mundo, então serve de base para o pid
    return Player(
        pid="g_" + codename.lower(),
        codename=codename,
        country=make_country(rng),
        role=role,
        age=age,
        tier=tier,
        skill=round(skill, 2),
        hidden={k: round(v, 2) for k, v in hidden.items()},
        hype=round(skill * 0.3, 2),
        form=0.0,
        club_id=None,
        contract=None,
        profile_ref=None,
    )
