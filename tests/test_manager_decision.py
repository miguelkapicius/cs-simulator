"""Testes da decisão do jogador entre ofertas."""
from manager.decision import choose_offer, score_offer
from manager.models import Club, Offer, Player
from manager.params import load_params
from manager.valuation import salary_for


def player(pid="x", role="rifler", skill=60.0, tier=2, hype=30.0, age=22):
    return Player(pid, "k" + pid, "BR", role, age, tier, skill, {}, hype, 0.0, None, None, None)


def club(cid="c", prestige=50.0, reputation=50.0, tier=2):
    return Club(cid, "Clube " + cid, tier, 100000, prestige, reputation)


def roster_of(roles, skill=60.0):
    return [player("r%d" % i, role=r, skill=skill) for i, r in enumerate(roles)]


def market_offer(p, cid, factor=1.0, prm=None):
    prm = prm or load_params()
    return Offer(cid, int(salary_for(p.tier, p.skill, p.hype, prm) * factor), 0, 48, p.role)


def test_awper_prefers_the_club_without_a_star_awper():
    prm = load_params()
    p = player(role="awper", skill=60.0)
    a, b = club("a"), club("b")
    ra = roster_of(["awper", "rifler", "rifler", "igl", "lurker"], skill=90.0)
    rb = roster_of(["rifler", "rifler", "rifler", "igl", "lurker"], skill=90.0)
    assert score_offer(p, market_offer(p, "b"), b, rb, prm) > score_offer(p, market_offer(p, "a"), a, ra, prm)


def test_reputation_can_beat_a_slightly_lower_salary():
    prm = load_params()
    p = player(tier=3, skill=50.0, age=19)
    rich, honest = club("rich", reputation=10), club("honest", reputation=90)
    low, high = market_offer(p, "honest", 0.9), market_offer(p, "rich", 1.0)
    assert score_offer(p, low, honest, [], prm) > score_offer(p, high, rich, [], prm)


def test_money_matters_less_to_stars():
    prm = load_params()
    c = club()
    star, rookie = player("s", skill=95.0, tier=1), player("r", skill=55.0, tier=1)
    delta = lambda pl: (score_offer(pl, market_offer(pl, "c", 1.5), c, [], prm)
                        - score_offer(pl, market_offer(pl, "c", 1.0), c, [], prm))
    assert delta(rookie) > delta(star)


def test_higher_salary_never_lowers_the_score():
    prm = load_params()
    p, c = player(), club()
    scores = [score_offer(p, market_offer(p, "c", f), c, [], prm) for f in (0.2, 0.6, 1.0, 1.5, 3.0)]
    assert scores == sorted(scores)


def test_choose_offer_picks_the_best_and_returns_none_below_threshold():
    prm = load_params()
    p = player()
    good, bad = club("good", prestige=80, reputation=80), club("bad", prestige=0, reputation=0)
    clubs = {"good": good, "bad": bad}
    offers = [market_offer(p, "bad", 0.1), market_offer(p, "good", 1.0)]
    assert choose_offer(p, offers, clubs, {}, prm).club_id == "good"
    assert choose_offer(p, [market_offer(p, "bad", 0.1)], clubs, {}, prm) is None


def test_choose_offer_with_no_offers_is_none():
    assert choose_offer(player(), [], {}, {}, load_params()) is None
