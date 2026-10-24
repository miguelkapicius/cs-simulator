"""Jogo do manager: cria o mundo, avança as semanas e aplica as ações do jogador.

As partidas semanais usam um modelo simples de força do time. Quando a simulação da Unity entregar
resultados reais, `_play_week` é o único ponto a substituir.
"""
import json
import math
import random
from pathlib import Path
from typing import Dict, List

from manager.calendar import is_market_window, opens_market_window, season_week, tournaments_for
from manager.decision import choose_offer
from manager.elite import elite_players
from manager.finance import can_afford, sticker_payout, weekly_revenue, weekly_wages
from manager.generate import generate_player
from manager.identity import make_codename
from manager.market import TEMPLATE, run_market_week, sign_player
from manager.models import Club, Contract, Offer, Player
from manager.params import load_params
from manager.valuation import apply_match_result, buyout_for, decay_hype, salary_for
from manager.world import Event, World

HUMAN_CID = "h"
ROSTER_SIZE = len(TEMPLATE)
STARTERS = 5
DECISION_EVENTS = {"contract_expiring", "market_open", "major", "season_end"}


def _rng(world: World) -> random.Random:
    rng = random.Random(world.seed)
    if world.rng_state is not None:
        s = world.rng_state
        rng.setstate((s[0], tuple(s[1]), s[2]))
    return rng


def _store_rng(world: World, rng: random.Random) -> None:
    s = rng.getstate()
    world.rng_state = [s[0], list(s[1]), s[2]]


def _hire(world: World, club: Club, player: Player, end_week: int, prm: Dict) -> None:
    salary = salary_for(player.tier, player.skill, player.hype, prm)
    player.club_id = club.cid
    player.contract = Contract(salary, 0, end_week, 0)
    player.contract.buyout = buyout_for(player, world.week, 1, prm)
    club.roster.append(player.pid)


def new_game(seed: int, difficulty: str, club_name: str) -> World:
    prm = load_params()
    g = prm["game"]
    if difficulty not in g["difficulty"]:
        raise ValueError("dificuldade desconhecida: %s" % difficulty)
    diff = g["difficulty"][difficulty]
    rng = random.Random(seed)
    elite = elite_players(seed)
    taken = {p.codename.lower() for p in elite}
    world = World(seed, 0, difficulty, {p.pid: p for p in elite}, {}, HUMAN_CID)
    awpers = [p for p in elite if p.role == "awper"]
    riflers = [p for p in elite if p.role != "awper"]

    def add(p: Player) -> Player:
        world.players[p.pid] = p
        return p

    ai_clubs = []
    for tier in (1, 2, 3):
        count = prm["tier_sizes"][str(tier)] - (1 if tier == 3 else 0)  # o clube do jogador ocupa uma vaga do Tier 3
        for _ in range(count):
            lo, hi = g["prestige"][str(tier)]
            name = make_codename(rng, taken).capitalize() + " " + rng.choice(["Esports", "Gaming", "Club", "Team"])
            club = Club("c%02d" % (len(ai_clubs) + 1), name, tier,
                        int(g["ai_budget"][str(tier)] * rng.uniform(0.8, 1.2)),
                        round(rng.uniform(lo, hi), 1), round(rng.uniform(40, 70), 1))
            ai_clubs.append(club)
            world.clubs[club.cid] = club
    for i in rng.sample(range(len(ai_clubs)), int(len(ai_clubs) * diff["aggressive_share"])):
        ai_clubs[i].style = "aggressive"

    for club in ai_clubs:
        for role in TEMPLATE:
            if club.tier == 1 and role == "awper" and awpers:
                p = awpers.pop()
            elif club.tier == 1 and role in ("entry", "support", "lurker", "rifler") and riflers:
                p = riflers.pop()
            else:
                p = add(generate_player(rng, club.tier, taken, role=role))
            _hire(world, club, p, rng.randint(24, 96), prm)

    human = Club(HUMAN_CID, club_name, 3, diff["human_budget"], g["human"]["prestige"], g["human"]["reputation"],
                 [], "conservative", True)
    world.clubs[HUMAN_CID] = human
    for role in TEMPLATE:  # elenco inicial fraco, para o jogador reformar
        p = add(generate_player(rng, 3, taken, role=role))
        p.skill = max(0.0, p.skill - 4)
        _hire(world, human, p, rng.randint(24, 72), prm)

    for tier, n in g["free_agents"].items():
        for _ in range(n):
            add(generate_player(rng, int(tier), taken))
    _store_rng(world, rng)
    return world


def _starters(club: Club, players: Dict[str, Player]) -> List[Player]:
    return sorted((players[pid] for pid in club.roster if players[pid].role != "coach"),
                  key=lambda p: (-p.skill, p.pid))[:STARTERS]


def _strength(club: Club, players: Dict[str, Player]) -> float:
    s = _starters(club, players)
    return sum(p.skill for p in s) / len(s) if s else 0.0


def _ranks(world: World, tier: int) -> Dict[str, int]:
    clubs = sorted((c for c in world.clubs.values() if c.tier == tier), key=lambda c: (-c.points, c.cid))
    return {c.cid: i + 1 for i, c in enumerate(clubs)}


def _play_week(world: World, tier: int, sw: int, rng: random.Random, prm: Dict) -> List[Event]:
    events = []
    clubs = sorted((c for c in world.clubs.values() if c.tier == tier), key=lambda c: c.cid)
    rng.shuffle(clubs)
    major = "major" in tournaments_for(sw, tier)
    for a, b in zip(clubs[0::2], clubs[1::2]):
        sa, sb = _strength(a, world.players), _strength(b, world.players)
        a_wins = rng.random() < 1 / (1 + math.exp(-(sa - sb) / prm["game"]["match_scale"]))
        (a if a_wins else b).points += 3
        for club, own, opp, won in ((a, sa, sb, a_wins), (b, sb, sa, not a_wins)):
            for p in _starters(club, world.players):
                rating = 1.0 + (0.1 if won else -0.1) + (p.skill - opp) / 200 + rng.gauss(0, 0.12)
                apply_match_result(p, max(0.2, min(2.0, rating)), won, major)
            if club.is_human:
                events.append(Event("match", world.week, {"won": won, "opponent": (b if club is a else a).cid}))
    return events


def _prize(pool: int, rank: int, size: int, weights: List[float]) -> int:
    if rank <= len(weights):
        return int(pool * weights[rank - 1])
    return int(pool * (1 - sum(weights)) / max(1, size - len(weights)))


def _finances(world: World, sw: int, prm: Dict) -> List[Event]:
    g, events = prm["game"], []
    for tier in (1, 2, 3):
        ranks = _ranks(world, tier)
        size = len(ranks)
        tournaments = tournaments_for(sw, tier)
        for cid, rank in ranks.items():
            club = world.clubs[cid]
            if len(_starters(club, world.players)) >= STARTERS:  # sem time completo não há patrocínio
                club.budget += weekly_revenue(club, rank, prm)
            club.budget -= weekly_wages(club, world.players)
            if "major" in tournaments:
                club.budget += sticker_payout(club, world.players, prm)
                club.budget += _prize(g["major_prize"], rank, size, g["prize_weights"])
            if "league_round" in tournaments:
                club.budget += _prize(g["prize_pool"][str(tier)], rank, size, g["prize_weights"])
            if not club.is_human:
                club.budget = max(0, club.budget)  # patrocinador de emergência: o clube do computador nunca quebra
            elif club.budget < 0:
                events.append(Event("in_debt", world.week, {"budget": club.budget}))
    return events


def _human_notices(world: World, sw: int, prm: Dict) -> List[Event]:
    g, events = prm["game"], []
    if opens_market_window(sw):
        events.append(Event("market_open", world.week, {"season_week": sw}))
    if sw in g["majors"]:
        events.append(Event("major", world.week, {"season_week": sw}))
    for pid in world.clubs[world.human_cid].roster:
        c = world.players[pid].contract
        if c and c.end_week - world.week == g["expiry_warning_weeks"]:
            events.append(Event("contract_expiring", world.week, {"pid": pid, "end_week": c.end_week}))
    return events


def _end_season(world: World, prm: Dict) -> List[Event]:
    g, events = prm["game"], []
    n = g["promote"]
    order = {}
    for t in (1, 2, 3):
        ranks = _ranks(world, t)
        order[t] = [world.clubs[cid] for cid in sorted(ranks, key=ranks.get)]  # do melhor para o pior
    moves = [(c, 2) for c in order[1][-n:]] + [(c, 1) for c in order[2][:n]] \
        + [(c, 3) for c in order[2][-n:]] + [(c, 2) for c in order[3][:n]]
    for club, tier in moves:
        events.append(Event("promoted" if tier < club.tier else "relegated", world.week,
                            {"cid": club.cid, "tier": tier}))
        club.tier = tier
    for club in world.clubs.values():
        club.points = 0
    for p in world.players.values():
        p.age += 1
        if p.age <= g["growth_max_age"] and p.hidden["ceiling"] > p.skill:
            p.skill = round(min(100.0, p.skill + min(g["growth_max"], (p.hidden["ceiling"] - p.skill)
                                                     * g["growth_rate"])), 2)
        elif p.age >= 31:
            p.skill = max(0.0, p.skill - 1)
    events.append(Event("season_end", world.week, {"season": world.week // prm["season_weeks"]}))
    return events


def advance_week(world: World) -> List[Event]:
    prm = load_params()
    rng = _rng(world)
    world.week += 1
    sw = season_week(world.week)
    events: List[Event] = []
    for tier in (1, 2, 3):
        events += _play_week(world, tier, sw, rng, prm)
    events += _finances(world, sw, prm)
    for p in world.players.values():
        p.hype = decay_hype(p.hype, 1, prm)
    events += run_market_week(world, rng, poaching=is_market_window(sw))
    events += _human_notices(world, sw, prm)
    if sw == prm["season_weeks"]:
        events += _end_season(world, prm)
    _store_rng(world, rng)
    return events


def advance_to_next_decision(world: World) -> List[Event]:
    """Avança semanas até um evento que pede decisão do jogador (ou o fim de uma temporada inteira)."""
    events: List[Event] = []
    for _ in range(load_params()["season_weeks"]):
        events += advance_week(world)
        if any(e.kind in DECISION_EVENTS for e in events):
            break
    return events


def make_offer(world: World, pid: str, offer: Offer) -> Event:
    """Oferta do clube do jogador: confere caixa, vaga no elenco e se o jogador aceita."""
    prm = load_params()
    human = world.clubs[world.human_cid]
    player = world.players.get(pid)

    def reject(reason: str) -> Event:
        return Event("offer_rejected", world.week, {"pid": pid, "reason": reason})

    if player is None:
        return reject("unknown_player")
    if offer.salary_month <= 0 or offer.signing_bonus < 0 or offer.weeks <= 0:
        return reject("invalid_offer")
    if offer.club_id != human.cid:
        return reject("not_your_club")
    if player.club_id == human.cid:
        return reject("already_yours")
    price = buyout_for(player, world.week, 1, prm) if player.club_id else 0
    if human.budget < offer.signing_bonus + price or not can_afford(human, world.players, offer, prm):
        return reject("cannot_afford")
    if len(human.roster) >= ROSTER_SIZE:
        return reject("roster_full")
    if choose_offer(player, [offer], world.clubs, world.players, prm) is None:
        return reject("declined")
    if player.club_id:
        seller = world.clubs[player.club_id]
        seller.roster.remove(pid)
        seller.budget += price
    human.budget -= offer.signing_bonus + price
    sign_player(world, human, player, offer, prm)
    return Event("signed", world.week, {"pid": pid, "cid": human.cid, "price": price})


def release_player(world: World, pid: str) -> Event:
    """Dispensa um jogador do clube do jogador pagando 8 semanas de salário."""
    prm = load_params()
    human = world.clubs[world.human_cid]
    if pid not in human.roster:
        return Event("release_rejected", world.week, {"pid": pid, "reason": "not_in_roster"})
    player = world.players[pid]
    cost = player.contract.salary_month // 4 * prm["cash_reserve_weeks"]
    if human.budget < cost:
        return Event("release_rejected", world.week, {"pid": pid, "reason": "cannot_afford"})
    human.budget -= cost
    human.roster.remove(pid)
    player.club_id, player.contract = None, None
    return Event("released_by_you", world.week, {"pid": pid, "cost": cost})


def save_game(world: World, path) -> None:
    Path(path).write_text(json.dumps(world.to_dict()), encoding="utf-8")


def load_game(path) -> World:
    return World.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
