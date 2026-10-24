"""Testes da valoração e das finanças do clube."""
from dataclasses import replace

from manager.finance import can_afford, sticker_payout, weekly_revenue, weekly_wages
from manager.models import Club, Contract, Offer, Player
from manager.params import load_params
from manager.valuation import apply_match_result, buyout_for, decay_hype, salary_for


def player(pid="p", tier=1, skill=85.0, hype=60.0, contract=None, club_id="c"):
    return Player(pid, "k" + pid, "BR", "rifler", 24, tier, skill, {}, hype, 0.0, club_id, contract, None)


def tiny_club(budget, weekly):
    """Clube cuja folha semanal é `weekly` (um jogador com salário mensal = 4 x weekly)."""
    p = player("w", contract=Contract(weekly * 4, 0, 96, 0))
    club = Club("c", "Tiny", 3, budget, 10.0, 50.0, ["w"])
    return club, {"w": p}


def test_salary_lands_inside_the_spec_bands():
    prm = load_params()
    assert 50000 <= salary_for(1, 95, 90, prm) <= 100000
    assert 15000 <= salary_for(1, 70, 30, prm) < 50000
    for t in (2, 3):
        assert 1000 <= salary_for(t, 60, 40, prm) <= 5000


def test_salary_stays_in_band_at_the_extremes():
    prm = load_params()
    assert salary_for(1, 100, 100, prm) <= 100000
    assert salary_for(3, 0, 0, prm) >= 1000


def test_salary_grows_with_skill_and_hype():
    prm = load_params()
    assert salary_for(1, 90, 50, prm) > salary_for(1, 75, 50, prm)
    assert salary_for(1, 80, 90, prm) > salary_for(1, 80, 10, prm)


def test_buyout_is_zero_without_contract_and_grows_with_interest():
    prm = load_params()
    p = player(contract=Contract(40000, 0, 96, 0))
    assert buyout_for(replace(p, contract=None), 10, 3, prm) == 0
    assert buyout_for(p, 10, 4, prm) > buyout_for(p, 10, 2, prm) > buyout_for(p, 10, 1, prm)


def test_buyout_falls_as_the_contract_runs_out():
    prm = load_params()
    p = player(contract=Contract(40000, 0, 96, 0))
    assert buyout_for(p, 80, 2, prm) < buyout_for(p, 10, 2, prm)
    assert buyout_for(p, 96, 2, prm) == 0


def test_hype_halves_after_the_half_life():
    prm = load_params()
    w = prm["hype_half_life_weeks"]
    assert abs(decay_hype(80.0, w, prm) - 40.0) < 0.5


def test_good_match_raises_hype_and_form_and_major_raises_more():
    a, b = player(hype=40.0), player(hype=40.0)
    apply_match_result(a, 1.4, True)
    apply_match_result(b, 1.4, True, major=True)
    assert a.form > 0 and a.hype > 40.0 and b.hype > a.hype


def test_bad_match_lowers_hype_but_not_below_zero():
    p = player(hype=1.0)
    apply_match_result(p, 0.5, False)
    assert p.hype == 0.0 and p.form < 0


def test_can_afford_rejects_offers_that_break_the_reserve():
    prm = load_params()
    club, players = tiny_club(budget=50000, weekly=3000)
    assert not can_afford(club, players, Offer(club.cid, 5000, 40000, 48, "rifler"), prm)
    assert can_afford(club, players, Offer(club.cid, 1500, 1000, 48, "rifler"), prm)


def test_weekly_wages_is_the_roster_salary_over_four_weeks():
    club, players = tiny_club(budget=1, weekly=3000)
    assert weekly_wages(club, players) == 3000


def test_better_rank_earns_more_sponsorship():
    prm = load_params()
    club = Club("c", "X", 2, 0, 0.0, 0.0)
    assert weekly_revenue(club, 1, prm) > weekly_revenue(club, 12, prm) > 0


def test_stickers_scale_with_hype_and_only_pay_tier_one():
    prm = load_params()
    hot = {str(i): player(str(i), hype=90.0) for i in range(5)}
    cold = {str(i): player(str(i), hype=10.0) for i in range(5)}
    club = Club("c", "X", 1, 0, 0.0, 0.0, list(hot))
    assert sticker_payout(club, hot, prm) > sticker_payout(club, cold, prm) > 0
    assert sticker_payout(replace(club, tier=3), hot, prm) == 0


def test_star_buyout_stays_near_the_real_record_scale():
    prm = load_params()
    star = player(tier=1, skill=97.0, hype=80.0, contract=Contract(60000, 0, 200, 0))
    assert 500_000 <= buyout_for(star, 10, 1, prm) <= 1_500_000   # recorde individual conhecido: ~US$ 1,1 mi
    assert buyout_for(star, 10, 6, prm) <= 3_000_000
