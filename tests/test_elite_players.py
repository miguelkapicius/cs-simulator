"""Artefato elite_players.json: o comportamento dos jogadores reais, sem nenhuma identidade real."""
import copy
import json
import re

import pytest
from jsonschema import Draft202012Validator

from pipeline import validate_contract
from pipeline.build_elite_players import build
from pipeline.common import ARTIFACTS_DIR, SCHEMAS_DIR


@pytest.fixture(scope="module")
def real():
    return json.load(open(ARTIFACTS_DIR / "player_profiles.json", encoding="utf-8"))["players"]


@pytest.fixture(scope="module")
def doc():
    return build()


def validator():
    schema = json.loads((SCHEMAS_DIR / "elite_players.schema.json").read_text())
    return Draft202012Validator(schema, registry=validate_contract.registry())


def test_has_one_player_per_real_profile_and_the_contract_header(doc, real):
    assert len(doc["players"]) == len(real) >= 40
    assert doc["schema_version"] == "1.0" and re.match(r"^\d+\.\d+\.\d+$", doc["contract_version"])


def test_no_real_identifier_anywhere_in_the_artifact(doc, real):
    dump = json.dumps(doc, ensure_ascii=False)
    for p in real:
        for ident in (p["name"], p["steamid"], p["team"]):
            assert '"%s"' % ident not in dump, ident
    assert not re.search(r"\d{17}", dump)
    assert "source" not in doc and not any(k in pl for pl in doc["players"] for k in ("name", "steamid", "team"))


def test_behavior_is_kept_exactly_from_the_real_profile(doc, real):
    in_profile_order = sorted(doc["players"], key=lambda p: int(p["pid"][1:]))
    for entry, prof in zip(in_profile_order, real):
        assert entry["profile"]["mechanics"] == prof["mechanics"]
        assert entry["profile"]["positions"] == prof["positions"]
        assert entry["profile"]["role_tags"] == prof["role_tags"]


def test_build_is_deterministic():
    assert build() == build()


def test_matches_the_schema(doc):
    assert not list(validator().iter_errors(doc))


@pytest.mark.parametrize("key", ["name", "steamid", "team"])
def test_schema_rejects_a_player_that_carries_an_identity_field(doc, key):
    bad = copy.deepcopy(doc)
    bad["players"][0][key] = "x"
    assert list(validator().iter_errors(bad))


def test_validate_contract_flags_a_leaked_identity(doc, real):
    assert validate_contract.check_elite_identity(doc) == []
    leaked = copy.deepcopy(doc)
    leaked["players"][3]["codename"] = real[0]["name"]
    assert validate_contract.check_elite_identity(leaked)
    leaked = copy.deepcopy(doc)
    leaked["players"][3]["profile"]["note"] = real[1]["steamid"]
    assert validate_contract.check_elite_identity(leaked)
