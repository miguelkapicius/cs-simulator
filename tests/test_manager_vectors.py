"""Vetores de teste da economia do manager: entradas e saídas esperadas para o port em C# conferir."""
import copy
import json

import pytest

from pipeline import build_manager_vectors as bmv
from pipeline import validate_contract
from pipeline.common import VECTORS_DIR

GROUPS = {"salary_for", "buyout_for", "decay_hype", "match_update", "weekly_wages", "weekly_revenue", "sticker_payout",
          "can_afford", "team_strength", "role_term", "score_offer", "accepts", "scout_noise", "scout_numbers"}


@pytest.fixture(scope="module")
def doc():
    return bmv.build()


def test_there_is_a_group_of_cases_for_every_reference_function(doc):
    assert GROUPS <= set(doc) and all(len(doc[g]) >= 3 for g in GROUPS)
    assert sum(len(doc[g]) for g in GROUPS) >= 400


def test_cases_carry_input_and_expected_and_are_deterministic(doc):
    for g in GROUPS:
        assert all(set(c) == {"input", "expected"} for c in doc[g]), g
    again = bmv.build()
    assert {k: v for k, v in doc.items() if k != "generated_at"} == {k: v for k, v in again.items() if k != "generated_at"}


def test_the_cases_exercise_the_edges(doc):
    assert {c["expected"] for c in doc["accepts"]} == {True, False}
    assert {c["expected"] for c in doc["can_afford"]} == {True, False}
    assert min(c["expected"] for c in doc["buyout_for"]) == 0
    assert {c["input"]["tier"] for c in doc["salary_for"]} == {1, 2, 3}
    assert any(c["input"]["roster"] == [] for c in doc["team_strength"])


def test_committed_vectors_match_the_reference():
    assert validate_contract.check_manager_vectors() == []


def test_validator_flags_a_wrong_number_a_wrong_boolean_and_stale_params(tmp_path, monkeypatch):
    vec = json.loads((VECTORS_DIR / "manager_economy_vectors.json").read_text())

    def problems_for(mutated):
        (tmp_path / "manager_economy_vectors.json").write_text(json.dumps(mutated))
        monkeypatch.setattr(validate_contract, "VECTORS_DIR", tmp_path)
        return validate_contract.check_manager_vectors()

    bad = copy.deepcopy(vec); bad["salary_for"][3]["expected"] += 1
    assert any("salary_for[3]" in p for p in problems_for(bad))
    bad = copy.deepcopy(vec); bad["accepts"][0]["expected"] = not bad["accepts"][0]["expected"]
    assert any("accepts[0]" in p for p in problems_for(bad))
    bad = copy.deepcopy(vec); bad["score_offer"][5]["expected"] += 1e-6
    assert any("score_offer[5]" in p for p in problems_for(bad))
    bad = copy.deepcopy(vec); bad["params_sha256"] = "0" * 64
    assert any("params_sha256" in p for p in problems_for(bad))
