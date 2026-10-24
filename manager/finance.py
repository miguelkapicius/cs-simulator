"""Finanças do clube. As fórmulas são a referência do contrato; aqui só ligam os objetos do jogo a elas."""
from typing import Dict

from contract.reference import manager_economy as eco
from manager.models import Club, Offer, Player

WEEKS_PER_MONTH = eco.WEEKS_PER_MONTH


def weekly_wages(club: Club, players: Dict[str, Player]) -> int:
    return eco.weekly_wages([players[pid].contract.salary_month for pid in club.roster
                             if pid in players and players[pid].contract])


def weekly_revenue(club: Club, rank: int, prm: Dict) -> int:
    return eco.weekly_revenue(club.tier, rank, prm)


def sticker_payout(club: Club, players: Dict[str, Player], prm: Dict) -> int:
    return eco.sticker_payout(club.tier, [players[pid].hype for pid in club.roster if pid in players], prm)


def can_afford(club: Club, players: Dict[str, Player], offer: Offer, prm: Dict) -> bool:
    return eco.can_afford(club.budget, weekly_wages(club, players), offer.salary_month, offer.signing_bonus, prm)
