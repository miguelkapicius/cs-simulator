"""Referência pura da economia do manager (contract/reference/manager_economy.py): entradas simples, sem classes."""
import hashlib

import pytest

from contract.reference import manager_economy as eco
from manager.params import load_params

PRM = load_params()


def test_salary_values_are_pinned():
    cases = [((1, 95, 90), 86833), ((1, 70, 30), 27950), ((1, 85, 50), 57500), ((2, 60, 40), 3160),
             ((3, 48, 14), 2176), ((3, 0, 0), 1000), ((1, 100, 100), 100000)]
    for args, expected in cases:
        assert eco.salary_for(*args, PRM) == expected, args


def test_buyout_values_are_pinned_and_zero_without_a_running_contract():
    # (salary_month, hype, end_week, week, interested)
    cases = [((40000, 60, 96, 10, 1), 780000), ((40000, 60, 96, 10, 4), 1131000), ((40000, 80, 96, 0, 1), 840000),
             ((40000, 10, 96, 90, 2), 72450), ((40000, 60, 96, 96, 3), 0), ((40000, 60, 96, 200, 1), 0)]
    for args, expected in cases:
        assert eco.buyout_for(*args, PRM) == expected, args


def test_hype_decay_is_pinned():
    for (h, w), expected in [((80, 12), 40.0), ((50, 1), 47.193715634), ((100, 48), 6.25), ((0, 5), 0.0)]:
        assert eco.decay_hype(h, w, PRM) == pytest.approx(expected, abs=1e-8)


def test_match_update_moves_hype_and_form_and_clamps_hype():
    h, f = eco.match_update(40.0, 0.0, 1.4, True, False, PRM)
    h_major, _ = eco.match_update(40.0, 0.0, 1.4, True, True, PRM)
    assert h > 40.0 and f > 0 and h_major > h
    assert eco.match_update(1.0, 0.0, 0.5, False, False, PRM)[0] == 0.0
    assert eco.match_update(99.0, 0.0, 2.0, True, True, PRM)[0] == 100.0


def test_revenue_stickers_wages_and_reserve_are_pinned():
    rev = [eco.weekly_revenue(t, r, PRM) for t, r in [(1, 1), (1, 10), (2, 1), (2, 12), (3, 16), (3, 99)]]
    assert rev == [91000, 49000, 7800, 4200, 3150, 3150]
    assert [eco.sticker_payout(t, [20.0, 50.0, 90.0], PRM) for t in (1, 2, 3)] == [800000, 0, 0]
    assert eco.sticker_payout(1, [], PRM) == 0
    assert eco.weekly_wages([12000, 4000, 3999]) == 4999
    assert eco.can_afford(50000, 3000, 5000, 40000, PRM) is False
    assert eco.can_afford(50000, 3000, 1500, 1000, PRM) is True
    assert eco.can_afford(30000, 3000, 0, 0, PRM) is True


ROSTER = [{"role": "awper", "skill": 80.0}, {"role": "rifler", "skill": 60.0},
          {"role": "igl", "skill": 55.0}, {"role": "coach", "skill": 90.0}]
PLAYER = {"tier": 2, "skill": 62.0, "hype": 30.0, "role": "awper"}
CLUB = {"tier": 2, "prestige": 55.0, "reputation": 70.0}


def test_score_offer_values_are_pinned():
    got = [eco.score_offer(PLAYER, s, CLUB, ROSTER, PRM) for s in (1000, 3000, 6000)]
    assert got == pytest.approx([0.398843072, 0.517217291, 0.576149606], abs=1e-8)


def test_team_strength_ignores_the_coach_and_falls_back_to_the_tier_mean_for_an_empty_roster():
    assert eco.team_strength(2, ROSTER, PRM) == pytest.approx(0.65)
    assert eco.team_strength(2, [], PRM) == PRM["generator"]["skill_mean"]["2"] / 100


def test_role_term_has_three_levels():
    assert eco.role_term("rifler", 60.0, ROSTER, PRM) == 1.0           # há vaga (cap 2, um rifler)
    assert eco.role_term("awper", 90.0, ROSTER, PRM) == 0.5            # função cheia, mas ele seria titular
    assert eco.role_term("awper", 70.0, ROSTER, PRM) == 0.0            # função cheia e ele seria reserva


def test_accepts_uses_a_strict_threshold():
    t = PRM["accept_threshold"]
    assert eco.accepts(t + 1e-9, PRM) and not eco.accepts(t, PRM)


def test_scout_noise_is_the_documented_sha256_formula():
    digest = hashlib.sha256(b"42:g_kozen:2:skill").digest()
    u = int.from_bytes(digest[:8], "big") / 2 ** 64
    assert eco.scout_noise(42, "g_kozen", 2, "skill", 4.0) == (2 * u - 1) * 4.0
    assert eco.scout_noise(42, "g_kozen", 2, "skill", 4.0) == eco.scout_noise(42, "g_kozen", 2, "skill", 4.0)
    assert abs(eco.scout_noise(7, "x", 0, "skill", 12.0)) <= 12.0


def test_scout_numbers_reveal_by_level_and_stay_in_range():
    hidden = {"consistency": 99.0, "communication": 1.0, "ceiling": 50.0, "lan_form": 50.0, "temperament": 50.0}
    assert set(eco.scout_numbers(60.0, hidden, "p", 0, 1, PRM)) == {"skill_estimate"}
    assert set(eco.scout_numbers(60.0, hidden, "p", 1, 1, PRM)) == {"skill_estimate", "consistency"}
    assert set(eco.scout_numbers(60.0, hidden, "p", 3, 1, PRM)) == {"skill_estimate", *hidden}
    for level in range(4):
        for v in eco.scout_numbers(99.5, hidden, "p", level, 1, PRM).values():
            assert 0.0 <= v <= 100.0
