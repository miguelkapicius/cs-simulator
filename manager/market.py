"""Mercado semanal: contratos que vencem, clubes do computador que fazem ofertas e jogadores que escolhem."""
import random
from typing import Dict, List, Optional, Tuple

from manager.decision import choose_offer
from manager.finance import can_afford, weekly_wages
from manager.generate import generate_player
from manager.models import Club, Contract, Offer, Player
from manager.params import load_params
from manager.valuation import buyout_for, salary_for
from manager.world import Event, World

TEMPLATE = ["awper", "igl", "entry", "support", "lurker", "rifler", "coach"]  # 5 titulares + reserva + coach


def ai_needs(club: Club, players: Dict[str, Player]) -> List[str]:
    """Funções que faltam para fechar 7 pessoas: primeiro as do modelo que ninguém cobre, depois riflers."""
    slots = len(TEMPLATE) - len(club.roster)
    if slots <= 0:
        return []
    have = [players[pid].role for pid in club.roster if pid in players]
    missing = []
    for role in TEMPLATE:
        if role in have:
            have.remove(role)
        else:
            missing.append(role)
    return (missing + ["rifler"] * len(TEMPLATE))[:slots]


def _sign(world: World, club: Club, player: Player, offer: Offer, prm: Dict) -> None:
    player.club_id = club.cid
    player.contract = Contract(offer.salary_month, offer.signing_bonus, world.week + offer.weeks,
                               buyout_for(player, world.week, 1, prm))
    club.roster.append(player.pid)


def _expire_contracts(world: World) -> List[Event]:
    events = []
    for pid in sorted(world.players):
        p = world.players[pid]
        if p.contract and p.club_id and p.contract.end_week <= world.week:
            world.clubs[p.club_id].roster.remove(pid)
            events.append(Event("contract_expired", world.week, {"pid": pid, "cid": p.club_id}))
            p.club_id, p.contract = None, None
    return events


def _release_overpaid(world: World, prm: Dict) -> List[Event]:
    """Clube do computador sem caixa para a reserva dispensa o jogador mais caro."""
    events = []
    for cid in sorted(world.clubs):
        club = world.clubs[cid]
        if club.is_human or not club.roster:
            continue
        if club.budget < prm["cash_reserve_weeks"] * weekly_wages(club, world.players):
            pid = max(club.roster, key=lambda x: (world.players[x].contract.salary_month, x))
            club.roster.remove(pid)
            p = world.players[pid]
            p.club_id, p.contract = None, None
            events.append(Event("released", world.week, {"pid": pid, "cid": cid}))
    return events


def _tier_ok(club: Club, player: Player) -> bool:
    reach = 1 if club.style == "aggressive" else 0
    return player.tier >= club.tier - reach


def _make_offer(club: Club, player: Player, prm: Dict) -> Offer:
    m = prm["market"]
    salary = int(salary_for(player.tier, player.skill, player.hype, prm) * m["style_premium"][club.style])
    return Offer(club.cid, salary, salary * m["bonus_months"], m["offer_weeks"], player.role)


def _pick_target(world: World, club: Club, role: str, targeted: set, prm: Dict) -> Optional[Tuple[Player, Offer]]:
    m = prm["market"]
    budget_cap = club.budget * m["style_spend"][club.style]
    free = sorted((p for p in world.players.values() if p.club_id is None and p.role == role
                   and _tier_ok(club, p) and p.pid not in targeted), key=lambda p: (-p.skill, p.pid))
    held = sorted((p for p in world.players.values()
                   if p.club_id not in (None, club.cid, world.human_cid) and p.role == role
                   and _tier_ok(club, p) and p.pid not in targeted), key=lambda p: (-p.skill, p.pid))
    margin = m["poach_margin"][club.style]
    floor = free[0].skill + margin if free else float("-inf")
    for p in [h for h in held if h.skill >= floor] + free:
        offer = _make_offer(club, p, prm)
        cost = offer.signing_bonus + (buyout_for(p, world.week, 1, prm) if p.club_id else 0)
        if cost <= budget_cap and can_afford(club, world.players, offer, prm):
            return p, offer
    return None


def fill_roster_with_free_agents(world: World, club: Club, rng: random.Random) -> None:
    """Garantia final: completa o elenco com jogadores novos do tier do clube, em contrato mínimo sem bônus."""
    prm = load_params()
    for role in ai_needs(club, world.players):
        p = generate_player(rng, club.tier, world.taken_names(), role=role)
        world.players[p.pid] = p
        salary = salary_for(p.tier, p.skill, p.hype, prm)
        _sign(world, club, p, Offer(club.cid, salary, 0, prm["market"]["offer_weeks"], role), prm)


def run_market_week(world: World, rng: random.Random) -> List[Event]:
    prm = load_params()
    events = _expire_contracts(world) + _release_overpaid(world, prm)

    # fase 1: cada clube do computador escolhe um alvo por necessidade
    bids: Dict[str, List[Offer]] = {}
    for cid in sorted(world.clubs):
        club = world.clubs[cid]
        if club.is_human:
            continue
        targeted: set = set()
        for role in ai_needs(club, world.players):
            pick = _pick_target(world, club, role, targeted, prm)
            if pick:
                targeted.add(pick[0].pid)
                bids.setdefault(pick[0].pid, []).append(pick[1])

    # fase 2: o preço da buyout sobe com o número de interessados; o jogador escolhe a melhor oferta
    for pid in sorted(bids):
        player = world.players[pid]
        offers = list(bids[pid])
        price = buyout_for(player, world.week, len(offers), prm) if player.club_id else 0
        while offers:
            choice = choose_offer(player, offers, world.clubs, world.players, prm)
            if choice is None:
                break
            buyer = world.clubs[choice.club_id]
            if buyer.budget >= choice.signing_bonus + price and can_afford(buyer, world.players, choice, prm):
                if player.club_id:
                    seller = world.clubs[player.club_id]
                    seller.roster.remove(pid)
                    seller.budget += price
                buyer.budget -= choice.signing_bonus + price
                _sign(world, buyer, player, choice, prm)
                events.append(Event("signed", world.week, {"pid": pid, "cid": buyer.cid, "price": price,
                                                           "interested": len(bids[pid])}))
                break
            offers.remove(choice)

    for cid in sorted(world.clubs):
        club = world.clubs[cid]
        if not club.is_human:
            fill_roster_with_free_agents(world, club, rng)
    return events
