"""Testes do mercado com clubes do computador."""
import random

from manager.generate import generate_player
from manager.market import ai_needs, run_market_week
from manager.models import Club, Contract
from manager.params import load_params
from manager.valuation import salary_for
from manager.world import World

TEMPLATE = ["awper", "igl", "entry", "support", "lurker", "rifler", "coach"]


def hire(world, club, player):
    prm = load_params()
    player.club_id = club.cid
    player.contract = Contract(salary_for(player.tier, player.skill, player.hype, prm), 0, world.week + 96, 0)
    club.roster.append(player.pid)


def small_world(seed, tier=3, clubs=3, free_agents=12, budget=200000, style="conservative"):
    rng, taken = random.Random(seed), set()
    w = World(seed=seed, week=0, difficulty="normal", players={}, clubs={}, human_cid="h")
    for i in range(clubs):
        club = Club("c%d" % (i + 1), "Clube %d" % i, tier, budget, 40.0, 50.0, [], style)
        w.clubs[club.cid] = club
        for role in TEMPLATE:
            p = generate_player(rng, tier, taken, role=role)
            w.players[p.pid] = p
            hire(w, club, p)
    for _ in range(free_agents):
        p = generate_player(rng, tier, taken)
        w.players[p.pid] = p
    return w


def remove_player(w, cid, role):
    club = w.clubs[cid]
    pid = next(pid for pid in club.roster if w.players[pid].role == role)
    club.roster.remove(pid)
    w.players[pid].club_id, w.players[pid].contract = None, None
    return club


def test_ai_needs_lists_missing_roles():
    w = small_world(seed=1)
    club = remove_player(w, "c2", role="awper")
    assert ai_needs(club, w.players) == ["awper"]
    assert ai_needs(w.clubs["c1"], w.players) == []


def test_roster_is_refilled_after_a_departure():            # Review Focus 1
    w = small_world(seed=1, free_agents=0)
    remove_player(w, "c2", "awper"); remove_player(w, "c2", "igl")
    w.players = {pid: p for pid, p in w.players.items() if p.club_id is not None}  # nobody free to sign
    run_market_week(w, random.Random(2))
    assert len(w.clubs["c2"].roster) == 7
    assert all(w.players[pid].club_id == "c2" for pid in w.clubs["c2"].roster)


def price_paid(interested):
    w = small_world(seed=3, tier=1, clubs=interested + 1, free_agents=0, budget=50_000_000, style="aggressive")
    seller = w.clubs["c1"]
    star_pid = next(pid for pid in seller.roster if w.players[pid].role == "awper")
    star = w.players[star_pid]
    star.skill, star.hype = 97.0, 80.0
    star.contract = Contract(60000, 0, 200, 0)
    for cid in list(w.clubs):
        if cid != "c1":
            remove_player(w, cid, "awper")      # the others each lack an awper
    w.players = {pid: p for pid, p in w.players.items() if p.club_id is not None or p.role != "awper"}
    events = run_market_week(w, random.Random(1))
    sale = [e for e in events if e.kind == "signed" and e.data["pid"] == star_pid]
    assert len(sale) == 1 and sale[0].data["price"] > 0
    return sale[0].data["price"]


def test_more_interested_clubs_raise_the_price():
    assert price_paid(4) > price_paid(1)


def test_market_never_leaves_an_ai_club_with_negative_budget():
    w = small_world(seed=4)
    for week in range(60):
        w.week = week
        run_market_week(w, random.Random(week))
    assert all(c.budget >= 0 for c in w.clubs.values())
    assert all(len(c.roster) == 7 for c in w.clubs.values())


def test_expired_contracts_free_the_player():
    w = small_world(seed=5)
    pid = w.clubs["c1"].roster[0]
    w.players[pid].contract.end_week = 0
    w.week = 1
    events = run_market_week(w, random.Random(1))
    assert any(e.kind == "contract_expired" and e.data["pid"] == pid for e in events)
    assert len(w.clubs["c1"].roster) == 7


def test_market_is_deterministic():
    a, b = small_world(seed=9), small_world(seed=9)
    run_market_week(a, random.Random(1)); run_market_week(b, random.Random(1))
    assert a.to_dict() == b.to_dict()


def test_world_roundtrip():
    w = small_world(seed=2)
    assert World.from_dict(w.to_dict()).to_dict() == w.to_dict()
