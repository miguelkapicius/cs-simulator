"""Decisão do jogador entre ofertas. A nota é a referência do contrato; aqui só ligam os objetos do jogo a ela."""
from typing import Dict, List, Optional

from contract.reference import manager_economy as eco
from manager.models import Club, Offer, Player


def _view(p: Player) -> Dict:
    return {"role": p.role, "skill": p.skill}


def score_offer(player: Player, offer: Offer, club: Club, roster: List[Player], prm: Dict) -> float:
    return eco.score_offer({"tier": player.tier, "skill": player.skill, "hype": player.hype, "role": player.role},
                           offer.salary_month,
                           {"tier": club.tier, "prestige": club.prestige, "reputation": club.reputation},
                           [_view(p) for p in roster], prm)


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
