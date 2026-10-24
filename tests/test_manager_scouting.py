"""Testes do scouting: informação imperfeita que melhora com o nível."""
import random

from manager.generate import generate_player
from manager.models import HIDDEN_KEYS
from manager.params import load_params
from manager.scouting import scout_cost, scout_view


def sample_player(i=0):
    return generate_player(random.Random(i), 2, set())


def test_same_view_twice_returns_the_same_numbers():         # Review Focus 3
    p = sample_player()
    assert scout_view(p, 1, 42) == scout_view(p, 1, 42)


def test_noise_differs_between_players():
    a, b = sample_player(1), sample_player(2)
    ea = scout_view(a, 0, 7)["skill_estimate"] - a.skill
    eb = scout_view(b, 0, 7)["skill_estimate"] - b.skill
    assert ea != eb


def test_higher_level_is_closer_to_the_truth_on_average():
    ps = [sample_player(i) for i in range(300)]
    err = lambda lv: sum(abs(scout_view(p, lv, 7)["skill_estimate"] - p.skill) for p in ps) / 300
    assert err(3) < err(2) < err(1) < err(0)


def test_hidden_attributes_are_revealed_by_level():
    p = sample_player()
    assert "consistency" not in scout_view(p, 0, 1)
    v1 = scout_view(p, 1, 1)
    assert "consistency" in v1 and "ceiling" not in v1
    v2 = scout_view(p, 2, 1)
    assert {"consistency", "communication", "ceiling"} <= set(v2) and "temperament" not in v2
    assert set(HIDDEN_KEYS) <= set(scout_view(p, 3, 1))


def test_public_info_is_always_visible_and_never_leaks_true_skill():
    p = sample_player()
    v = scout_view(p, 0, 1)
    assert {"pid", "codename", "role", "age", "hype", "skill_estimate"} <= set(v)
    assert "skill" not in v and "hidden" not in v


def test_cost_rises_with_level():
    prm = load_params()
    costs = [scout_cost(lv, prm) for lv in (1, 2, 3)]
    assert costs[0]["money"] < costs[1]["money"] < costs[2]["money"]
    assert costs[0]["weeks"] <= costs[1]["weeks"] <= costs[2]["weeks"]
