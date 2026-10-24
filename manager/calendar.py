"""Calendário em semanas: temporada de 48 semanas, Majors do Tier 1 e janelas de mercado."""
from typing import List

from manager.params import load_params


def season_week(week: int) -> int:
    """Semana dentro da temporada, de 1 a 48 (a semana 48 fecha a temporada)."""
    return (week - 1) % load_params()["season_weeks"] + 1


def tournaments_for(sw: int, tier: int) -> List[str]:
    g = load_params()["game"]
    out = []
    if tier == 1 and sw in g["majors"]:
        out.append("major")
    if sw % g["league_round_every"] == 0:
        out.append("league_round")
    return out


def is_market_window(sw: int) -> bool:
    return any(lo <= sw <= hi for lo, hi in load_params()["game"]["windows"])


def opens_market_window(sw: int) -> bool:
    return any(sw == lo for lo, _ in load_params()["game"]["windows"])
