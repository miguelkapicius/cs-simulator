"""Valoração: salário, buyout e hype. Todo valor monetário é int."""
from typing import Dict

from manager.models import Player
from manager.params import load_params


def _frac(x: float, lo: float, hi: float) -> float:
    return max(0.0, min(1.0, (x - lo) / (hi - lo)))


def salary_for(tier: int, skill: float, hype: float, prm: Dict) -> int:
    """Salário mensal dentro da faixa do tier; Tier 1 usa a faixa 'star' a partir de skill 85."""
    bands, rng = prm["salary_bands"][str(tier)], prm["salary_skill_range"]
    if tier == 1:
        key = "star" if skill >= rng["star"][0] else "regular"
        lo, hi = bands[key]
        skill_norm = _frac(skill, *rng[key])
    else:
        lo, hi = bands["all"]
        skill_norm = _frac(skill, *rng["low"])
    blend = prm["salary_blend"]
    x = blend["skill"] * skill_norm + blend["hype"] * _frac(hype, 0, 100)
    return int(lo + x * (hi - lo))


def buyout_for(player: Player, week: int, interested: int, prm: Dict) -> int:
    """Salário anual x temporadas que restam (com teto) x (1 + hype) x inflação por clubes interessados."""
    if player.contract is None:
        return 0
    weeks_left = max(0, player.contract.end_week - week)
    annual = player.contract.salary_month * 12
    inflation = 1 + prm["buyout"]["interest_step"] * max(0, interested - 1)
    seasons_left = min(weeks_left / prm["season_weeks"], prm["buyout"]["max_seasons"])
    value = annual * seasons_left * (1 + player.hype / prm["buyout"]["hype_divisor"]) * inflation
    return int(value)


def decay_hype(hype: float, weeks: int, prm: Dict) -> float:
    return hype * 0.5 ** (weeks / prm["hype_half_life_weeks"])


def apply_match_result(player: Player, rating: float, won: bool, major: bool = False) -> None:
    """Atualiza forma e hype depois de uma partida; Major pesa mais no hype."""
    h = load_params()["hype_match"]
    player.form = (1 - h["form_blend"]) * player.form + h["form_blend"] * (rating - 1.0) * h["form_scale"]
    delta = (rating - 1.0) * h["per_rating_point"] + (h["win"] if won else h["loss"])
    if major:
        delta *= h["major_multiplier"]
    player.hype = max(0.0, min(100.0, player.hype + delta))
