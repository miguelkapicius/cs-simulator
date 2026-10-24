"""Testes do jogo: criação do mundo, calendário em semanas, ofertas do jogador e salvamento."""
import pytest

from manager.game import (advance_to_next_decision, advance_week, load_game, make_offer, new_game,
                          release_player, save_game)
from manager.models import Offer


def tier_sizes(w):
    return [sum(1 for c in w.clubs.values() if c.tier == t) for t in (1, 2, 3)]


def best_free_agent(w):
    return max((p for p in w.players.values() if p.club_id is None), key=lambda p: (p.skill, p.pid))


def cheap_free_agent(w, role=None):
    return min((p for p in w.players.values() if p.club_id is None and (role is None or p.role == role)),
               key=lambda p: (p.skill, p.pid))


def test_new_game_world_shape():
    w = new_game(1, "normal", "Aurora")
    assert tier_sizes(w) == [10, 12, 16]
    human = w.clubs[w.human_cid]
    assert human.tier == 3 and human.is_human and human.name == "Aurora"
    assert all(len(c.roster) == 7 for c in w.clubs.values())
    assert sum(1 for p in w.players.values() if p.profile_ref is not None) == 40
    assert 40 <= sum(1 for p in w.players.values() if p.club_id is None) <= 80


def test_new_game_is_deterministic_and_difficulty_changes_the_budget():
    assert new_game(1, "normal", "A").to_dict() == new_game(1, "normal", "A").to_dict()
    b = lambda d: new_game(1, d, "A").clubs["h"].budget
    assert b("easy") > b("normal") > b("hard")


def test_unknown_difficulty_is_rejected():
    with pytest.raises(ValueError):
        new_game(1, "impossible", "A")


def test_advance_to_next_decision_stops_before_the_season_ends():
    w = new_game(1, "normal", "Aurora")
    ev = advance_to_next_decision(w)
    assert ev and 0 < w.week < 48
    assert any(e.kind in ("contract_expiring", "market_open", "major") for e in ev)


def test_offer_the_club_cannot_pay_is_rejected_and_budget_stays_non_negative():   # Review Focus 2
    w = new_game(1, "hard", "Aurora")
    star = best_free_agent(w)
    before = w.clubs[w.human_cid].budget
    ev = make_offer(w, star.pid, Offer(w.human_cid, 100000, 500000, 48, star.role))
    assert ev.kind == "offer_rejected" and ev.data["reason"] == "cannot_afford"
    assert w.clubs[w.human_cid].budget == before >= 0


def test_full_roster_blocks_a_signing_until_someone_is_released():
    w = new_game(1, "normal", "Aurora")
    free = cheap_free_agent(w)
    offer = Offer(w.human_cid, 2000, 0, 48, free.role)
    assert make_offer(w, free.pid, offer).data["reason"] == "roster_full"
    human = w.clubs[w.human_cid]
    release_player(w, human.roster[0])
    assert len(human.roster) == 6
    ev = make_offer(w, free.pid, Offer(w.human_cid, 6000, 0, 48, free.role))
    assert ev.kind in ("signed", "offer_rejected")
    if ev.kind == "signed":
        assert len(human.roster) == 7 and w.players[free.pid].club_id == w.human_cid


def test_save_load_continues_identically(tmp_path):                   # Review Focus 4
    a = new_game(3, "normal", "Aurora")
    for _ in range(10):
        advance_week(a)
    save_game(a, tmp_path / "s.json")
    b = load_game(tmp_path / "s.json")
    assert a.to_dict() == b.to_dict()
    for _ in range(20):
        advance_week(a)
        advance_week(b)
    assert a.to_dict() == b.to_dict()


def test_promotion_and_relegation_keep_the_tier_sizes():
    w = new_game(2, "normal", "Aurora")
    for _ in range(48):
        advance_week(w)
    assert tier_sizes(w) == [10, 12, 16]
    assert all(c.points == 0 for c in w.clubs.values())


def test_full_season_keeps_every_ai_club_at_7_people_and_solvent():
    w = new_game(2, "normal", "Aurora")
    for _ in range(48):
        advance_week(w)
    assert all(len(c.roster) == 7 for c in w.clubs.values() if not c.is_human)
    assert all(c.budget >= 0 for c in w.clubs.values() if not c.is_human)


def test_young_high_ceiling_players_grow_over_a_season():
    w = new_game(4, "normal", "Aurora")
    talents = {p.pid: p.skill for p in w.players.values() if p.hidden["ceiling"] >= 85 and p.age <= 20}
    assert talents
    for _ in range(48):
        advance_week(w)
    assert sum(w.players[pid].skill - s for pid, s in talents.items()) > 0


def test_a_club_without_a_squad_earns_no_sponsorship():
    w = new_game(1, "normal", "Aurora")
    human = w.clubs[w.human_cid]
    for pid in list(human.roster):
        release_player(w, pid)
    before = human.budget
    advance_week(w)
    assert human.budget == before
