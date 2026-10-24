"""manager_params.json: os números da economia como artefato do contrato, com schema e validação."""
import copy
import json

from jsonschema import Draft202012Validator

from manager.params import load_params
from pipeline import validate_contract
from pipeline.common import ARTIFACTS_DIR, SCHEMAS_DIR

PATH = ARTIFACTS_DIR / "manager_params.json"


def doc():
    return json.loads(PATH.read_text(encoding="utf-8"))


def errors(d):
    schema = json.loads((SCHEMAS_DIR / "manager_params.schema.json").read_text())
    return list(Draft202012Validator(schema, registry=validate_contract.registry()).iter_errors(d))


def test_artifact_has_the_contract_header_and_matches_the_schema():
    d = doc()
    assert d["schema_version"] == "1.0" and d["contract_version"].count(".") == 2
    assert errors(d) == []


def test_loader_returns_the_params_block_without_the_header():
    prm = load_params()
    assert prm == doc()["params"]
    assert "contract_version" not in prm and prm["season_weeks"] == 48


def test_the_old_copy_inside_the_package_is_gone():
    assert not (ARTIFACTS_DIR.parent.parent / "manager" / "params.json").exists()


def test_schema_rejects_a_missing_or_mistyped_parameter():
    d = doc()
    del d["params"]["buyout"]["max_seasons"]
    assert errors(d)
    d = doc()
    d["params"]["salary_bands"]["1"]["star"] = [100000, 50000, 1]
    assert errors(d)
    d = doc()
    d["params"]["accept_threshold"] = "0.4"
    assert errors(d)


def test_validator_checks_that_the_decision_weights_sum_to_one():
    assert validate_contract.check_manager_params(doc()) == []
    bad = copy.deepcopy(doc())
    bad["params"]["weights"]["money"] = 0.9
    problems = validate_contract.check_manager_params(bad)
    assert len(problems) == 1 and "weights" in problems[0]


def test_validator_checks_that_salary_bands_do_not_overlap_upward():
    bad = copy.deepcopy(doc())
    bad["params"]["salary_bands"]["1"]["regular"] = [15000, 80000]   # passa do começo da faixa 'star'
    assert any("salary_bands" in p for p in validate_contract.check_manager_params(bad))
