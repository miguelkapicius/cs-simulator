"""Finanças do clube: folha, receita e a regra da reserva de caixa."""
from typing import Dict

from manager.models import Club, Offer, Player

WEEKS_PER_MONTH = 4  # 48 semanas / 12 meses


def weekly_wages(club: Club, players: Dict[str, Player]) -> int:
    total = sum(players[pid].contract.salary_month for pid in club.roster
                if pid in players and players[pid].contract)
    return total // WEEKS_PER_MONTH


def weekly_revenue(club: Club, rank: int, prm: Dict) -> int:
    """Patrocínio fixo do tier, ajustado linearmente pelo ranking dentro do tier (1 = melhor)."""
    hi, lo = prm["rank_factor"]
    size = prm["tier_sizes"][str(club.tier)]
    pos = (min(max(rank, 1), size) - 1) / max(1, size - 1)
    return int(prm["sponsor_week"][str(club.tier)] * (hi + (lo - hi) * pos))


def sticker_payout(club: Club, players: Dict[str, Player], prm: Dict) -> int:
    """Repasse de stickers de um Major: proporcional ao hype médio do elenco; só o Tier 1 recebe."""
    pool = prm["sticker_pool"][str(club.tier)]
    hypes = [players[pid].hype for pid in club.roster if pid in players]
    if not pool or not hypes:
        return 0
    return int(pool * (sum(hypes) / len(hypes)) / 100)


def can_afford(club: Club, players: Dict[str, Player], offer: Offer, prm: Dict) -> bool:
    """Depois do bônus, o caixa precisa cobrir `cash_reserve_weeks` semanas da folha já com o novo salário."""
    weekly = weekly_wages(club, players) + offer.salary_month // WEEKS_PER_MONTH
    return club.budget - offer.signing_bonus >= prm["cash_reserve_weeks"] * weekly
