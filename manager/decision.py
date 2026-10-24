"""Decisão do jogador: pesa dinheiro, força do time, prestígio, função e reputação do manager."""
import math
from typing import Dict, List, Optional

from manager.models import Club, Offer, Player
from manager.valuation import salary_for

TOP_N = 5  # titulares que definem a força do time


def _team_strength(club: Club, roster: List[Player], prm: Dict) -> float:
    if not roster:
        return prm["generator"]["skill_mean"][str(club.tier)] / 100
    top = sorted((p.skill for p in roster if p.role != "coach"), reverse=True)[:TOP_N]
    return (sum(top) / len(top)) / 100 if top else 0.0


def _role_term(player: Player, roster: List[Player], prm: Dict) -> float:
    """1 se há vaga na função; 0.5 se ele entraria como titular de uma função cheia; 0 se seria reserva."""
    same = [r for r in roster if r.role == player.role]
    if len(same) < prm["role_cap"].get(player.role, 1):
        return 1.0
    return 0.5 if any(player.skill > r.skill for r in same) else 0.0


def score_offer(player: Player, offer: Offer, club: Club, roster: List[Player], prm: Dict) -> float:
    w = prm["weights"]
    market = max(1, salary_for(player.tier, player.skill, player.hype, prm))
    money = math.tanh(offer.salary_month / market)
    # quem já ganha muito liga menos para dinheiro
    money_weight = w["money"] * max(0.0, prm["money_star_discount"] - player.skill / 100)
    return (money_weight * money
            + w["team"] * _team_strength(club, roster, prm)
            + w["prestige"] * club.prestige / 100
            + w["role"] * _role_term(player, roster, prm)
            + w["reputation"] * club.reputation / 100)


def choose_offer(player: Player, offers: List[Offer], clubs: Dict[str, Club],
                 players: Dict[str, Player], prm: Dict) -> Optional[Offer]:
    best, best_score = None, prm["accept_threshold"]
    for offer in offers:
        club = clubs[offer.club_id]
        roster = [players[pid] for pid in club.roster if pid in players]
        s = score_offer(player, offer, club, roster, prm)
        if s > best_score:
            best, best_score = offer, s
    return best
