"""Integridade do mundo: sem identidade real, sem clubes travados, simulação de fumaça."""
import json

from manager.game import advance_week, new_game
from manager.sim import run
from tests.test_manager_identity import real_identifiers


def test_a_saved_world_contains_no_real_identifier():          # Review Focus 5
    w = new_game(1, "normal", "Aurora")
    for _ in range(30):
        advance_week(w)
    dump = json.dumps(w.to_dict())
    for ident in real_identifiers():
        assert '"%s"' % ident not in dump


def test_three_seasons_run_without_negative_ai_budget_or_stuck_clubs():
    w = new_game(5, "normal", "Aurora")
    for _ in range(3 * 48):
        advance_week(w)
    assert all(c.budget >= 0 for c in w.clubs.values() if not c.is_human)
    assert all(len(c.roster) == 7 for c in w.clubs.values() if not c.is_human)
    assert len({p.pid for p in w.players.values()}) == len(w.players)


def test_every_rostered_player_points_back_to_the_right_club():
    w = new_game(6, "hard", "Aurora")
    for _ in range(96):
        advance_week(w)
    for c in w.clubs.values():
        assert len(set(c.roster)) == len(c.roster)
        assert all(w.players[pid].club_id == c.cid and w.players[pid].contract for pid in c.roster)
    on_rosters = {pid for c in w.clubs.values() for pid in c.roster}
    assert all(p.club_id is None for pid, p in w.players.items() if pid not in on_rosters)


def test_sim_prints_one_block_per_season():
    lines = run(seed=1, seasons=2, difficulty="normal")
    assert sum(1 for l in lines if l.startswith("Temporada")) == 2
    assert any("transferências" in l for l in lines)
