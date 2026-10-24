"""Testes dos modelos e dos parâmetros da economia do manager."""
from manager.models import HIDDEN_KEYS, Contract, Player
from manager.params import load_params


def test_player_roundtrip():
    p = Player("p1", "kilo", "BR", "awper", 22, 2, 71.0, {k: 50.0 for k in HIDDEN_KEYS},
               30.0, 0.0, None, None, None)
    assert Player.from_dict(p.to_dict()) == p


def test_contract_roundtrip_inside_player():
    c = Contract(4000, 2000, 60, 30000)
    p = Player("p2", "z", "PL", "igl", 30, 3, 55.0, {k: 40.0 for k in HIDDEN_KEYS}, 5.0, 0.0, "c1", c, None)
    assert Player.from_dict(p.to_dict()).contract == c


def test_params_have_the_spec_bands():
    prm = load_params()
    assert prm["salary_bands"]["1"]["star"] == [50000, 100000]
    assert prm["salary_bands"]["1"]["regular"] == [15000, 50000]
    assert prm["salary_bands"]["2"]["all"] == [1000, 5000]
    assert prm["salary_bands"]["3"]["all"] == [1000, 5000]
    assert prm["season_weeks"] == 48 and prm["cash_reserve_weeks"] == 8
