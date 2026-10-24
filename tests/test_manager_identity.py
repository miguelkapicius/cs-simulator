"""Testes da identidade ficcional: nada do que é real pode chegar ao produto."""
import json
import random

from manager.elite import elite_players
from manager.identity import make_codename
from pipeline.common import ARTIFACTS_DIR


def real_identifiers():
    d = json.load(open(ARTIFACTS_DIR / "player_profiles.json", encoding="utf-8"))
    return {p["name"] for p in d["players"]} | {p["steamid"] for p in d["players"]}


def test_elite_has_40_players_and_no_real_identifier():
    players = elite_players(seed=1)
    assert len(players) == 40
    dump = json.dumps([p.to_dict() for p in players])
    for ident in real_identifiers():
        assert '"%s"' % ident not in dump


def test_codenames_never_equal_a_real_name():
    rng, taken = random.Random(3), set()
    names = {make_codename(rng, taken) for _ in range(500)}
    assert not (names & {i.lower() for i in real_identifiers()})
    assert len(names) == 500


def test_elite_is_deterministic_for_the_seed():
    assert [p.to_dict() for p in elite_players(7)] == [p.to_dict() for p in elite_players(7)]


def test_elite_skill_is_between_70_and_98():
    assert all(70 <= p.skill <= 98 for p in elite_players(1))


def test_elite_keeps_role_and_links_back_to_the_profile():
    players = elite_players(1)
    assert {p.profile_ref for p in players} == {str(i) for i in range(40)}
    assert any(p.role == "awper" for p in players)
