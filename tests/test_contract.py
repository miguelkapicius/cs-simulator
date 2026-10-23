"""Testes do contrato: artefatos, schemas, vetores de teste, log, métricas e comparador."""
import copy
import glob
import json
import random
import shutil
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from calibration.compare import DEFAULT_THRESHOLDS, compare, equivalent_matches
from calibration.metrics import compute_metrics
from calibration.simlog import load_tables
from calibration.validate_log import validate_file
from contract.reference import tactics as tac
from contract.reference import team_model as ref
from contract.reference import weapon_dynamics as wd
from pipeline import validate_contract
from pipeline.combat import resolve_sightings
from pipeline.common import ARTIFACTS_DIR, BUY_ECO_MAX, BUY_FORCE_MAX, DATA_DIR, EXAMPLES_DIR, buy_type

EXAMPLE = EXAMPLES_DIR / "sim_log_example.jsonl"
REAL_LOGS = sorted(glob.glob(str(DATA_DIR / "*" / "simlog.jsonl")))
needs_data = pytest.mark.skipif(len(REAL_LOGS) < 8, reason="logs reais (data/) não estão nesta máquina")


@pytest.fixture(scope="module")
def model():
    return json.loads((ARTIFACTS_DIR / "team_model.json").read_text())


# ---------- contrato ----------

def test_artifacts_match_schemas():
    assert validate_contract.check_artifacts(validate_contract.registry()) == []


def test_vectors_match_reference():
    assert validate_contract.check_vectors() == []


def test_weapon_vectors_match_reference():
    assert validate_contract.check_weapon_vectors() == []


def test_tactics_vectors_match_reference():
    assert validate_contract.check_tactics_vectors() == []


def test_example_log_is_valid():
    errors, warnings = validate_file(EXAMPLE)
    assert errors == [] and warnings == []


# ---------- validador de log ----------

def _write(tmp_path, lines):
    p = tmp_path / "bad.jsonl"
    p.write_text("\n".join(json.dumps(x) if not isinstance(x, str) else x for x in lines) + "\n")
    return p


def _events():
    return [json.loads(l) for l in EXAMPLE.read_text().splitlines()]


def test_validator_rejects_missing_field(tmp_path):
    ev = _events()
    del next(e for e in ev if e["type"] == "kill")["victim"]
    errors, _ = validate_file(_write(tmp_path, ev))
    assert any("victim" in e for e in errors)


def test_validator_rejects_round_gap_and_unknown_player(tmp_path):
    ev = _events()
    next(e for e in ev if e["type"] == "round_start" and e["round"] == 2)["round"] = 5
    errors, _ = validate_file(_write(tmp_path, ev))
    assert any("round_start" in e for e in errors)
    ev = _events()
    next(e for e in ev if e["type"] == "kill")["attacker"] = "999"
    errors, _ = validate_file(_write(tmp_path, ev))
    assert any("não está em match_start" in e for e in errors)


def test_validator_rejects_incompatible_major(tmp_path):
    ev = _events()
    ev[0]["contract_version"] = "9.0.0"
    errors, _ = validate_file(_write(tmp_path, ev))
    assert any("incompatível" in e for e in errors)


def test_validator_rejects_garbage(tmp_path):
    errors, _ = validate_file(_write(tmp_path, ["isto não é json"]))
    assert errors


# ---------- reação e duelo ----------

def test_resolve_sightings_reaction_and_outcome():
    sp = pd.DataFrame({"tick": [100], "observer": ["A"], "target": ["B"], "distance_m": [10.0], "aim_err_deg": [5.0]})
    shots = pd.DataFrame({"tick": [113], "shooter": ["A"], "target": ["B"], "aim_err_deg": [1.0], "hit": [True]})
    kills = pd.DataFrame({"tick": [140], "attacker_steamid": ["A"], "user_steamid": ["B"], "after_round_end": [False]})
    out = resolve_sightings(sp, shots, kills)
    assert out.loc[0, "reaction_s"] == pytest.approx(13 / 64) and out.loc[0, "outcome"] == "win"
    lost = resolve_sightings(sp, shots, pd.DataFrame({"tick": [140], "attacker_steamid": ["B"], "user_steamid": ["A"], "after_round_end": [False]}))
    assert lost.loc[0, "outcome"] == "loss"


def test_resolve_sightings_ignores_fight_in_progress():
    sp = pd.DataFrame({"tick": [100], "observer": ["A"], "target": ["B"], "distance_m": [10.0], "aim_err_deg": [5.0]})
    shots = pd.DataFrame({"tick": [90], "shooter": ["A"], "target": ["C"], "aim_err_deg": [1.0], "hit": [False]})
    kills = pd.DataFrame({"tick": [], "attacker_steamid": [], "user_steamid": [], "after_round_end": []})
    assert resolve_sightings(sp, shots, kills).empty


# ---------- métricas e comparador ----------

def test_metrics_on_example():
    t = load_tables([EXAMPLE])
    assert len(t["rounds"]) == 2 and len(t["players"]) == 20
    m = compute_metrics(t)
    assert "round.win_rate.CT" in m and m["round.win_rate.CT"]["n"] == 2
    assert 0 <= m["combat.accuracy.rifle"]["value"] <= 1


def test_compare_runs_and_marks_small_samples():
    targets = json.loads((ARTIFACTS_DIR / "calibration_targets.json").read_text())["metrics"]
    tables = load_tables([EXAMPLE])
    doc = json.loads((ARTIFACTS_DIR / "calibration_targets.json").read_text())
    total, by_map = equivalent_matches(tables["rounds"], doc)
    rows = compare(compute_metrics(tables), targets, DEFAULT_THRESHOLDS, by_map, total)
    assert len(rows) == len(targets)
    statuses = {r["status"] for r in rows}
    assert statuses <= {"OK", "WARN", "FAIL", "INSUFFICIENT", "MISSING"}
    assert "FAIL" not in statuses  # 2 rounds não bastam para reprovar nada


@needs_data
def test_comparator_few_false_alarms_and_catches_tampering():
    from calibration.build_targets import make_targets
    files = REAL_LOGS[:]
    random.Random(1).shuffle(files)
    _, targets = make_targets(files[:19])
    t = load_tables(files[19:])
    doc = {"source": {"rounds": len(load_tables(files[:19])["rounds"]), "matches": 19}}
    total, by_map = equivalent_matches(t["rounds"], doc)
    rows = compare(compute_metrics(t), targets, DEFAULT_THRESHOLDS, by_map, total)
    judged = [r for r in rows if r["status"] in ("OK", "WARN", "FAIL")]
    assert not [r for r in rows if r["status"] == "FAIL"]
    assert sum(r["status"] == "WARN" for r in judged) / len(judged) < 0.06

    tmp = Path(tempfile.mkdtemp())
    try:
        for i, f in enumerate(files[19:]):
            r2, out = random.Random(i), []
            for line in open(f):
                e = json.loads(line)
                if e["type"] == "shot" and e["hit"] and e["weapon"] in ("ak47", "m4a1", "m4a1_silencer", "galilar", "famas") and r2.random() < 0.5:
                    e["hit"] = False
                out.append(json.dumps(e))
            (tmp / f"m{i}.jsonl").write_text("\n".join(out) + "\n")
        t2 = load_tables(sorted(tmp.glob("*.jsonl")))
        total2, by_map2 = equivalent_matches(t2["rounds"], doc)
        rows2 = compare(compute_metrics(t2), targets, DEFAULT_THRESHOLDS, by_map2, total2)
    finally:
        shutil.rmtree(tmp)
    flagged = {r["id"] for r in rows2 if r["status"] in ("WARN", "FAIL")}
    assert "combat.accuracy.rifle" in flagged


# ---------- definições compartilhadas e modelo de time ----------

def test_buy_type_rule():
    assert buy_type(1, 5000) == "pistol" and buy_type(13, 100) == "pistol"
    assert buy_type(5, BUY_ECO_MAX - 1) == "eco"
    assert buy_type(5, BUY_ECO_MAX) == "force"
    assert buy_type(5, BUY_FORCE_MAX - 1) == "force"
    assert buy_type(5, BUY_FORCE_MAX) == "full"


def _state(**kw):
    s = {"map": "de_mirage", "round_time_s": 40.0, "alive_ct": 3, "alive_t": 3, "bomb_planted": False,
         "time_since_plant_s": None, "ct_equip_avg": 4500.0, "t_equip_avg": 4500.0}
    s.update(kw)
    return s


def test_win_probability_hard_rules_and_unknown_map(model):
    assert ref.win_probability(model, _state(alive_ct=0, bomb_planted=True, time_since_plant_s=3.0)) == 0.0
    assert ref.win_probability(model, _state(alive_t=0)) == 1.0
    assert 0 < ref.win_probability(model, _state(map="de_nao_existe")) < 1


def test_win_probability_is_monotonic(model):
    ps = [ref.win_probability(model, _state(alive_ct=n)) for n in range(1, 6)]
    assert ps == sorted(ps)
    ps = [ref.win_probability(model, _state(alive_t=n)) for n in range(1, 6)]
    assert ps == sorted(ps, reverse=True)
    assert ref.win_probability(model, _state(ct_equip_avg=6000)) > ref.win_probability(model, _state(ct_equip_avg=1500))


def test_buy_distribution_sums_to_one(model):
    for side in ("CT", "T"):
        for res in (500, 2000, 3000, 4000, 5000, 6000, 7000, 12000):
            d = ref.buy_distribution(model, {"side": side, "round": 7, "avg_resources_before": res})
            assert sum(d.values()) == pytest.approx(1.0, abs=2e-3)
    assert ref.buy_distribution(model, {"side": "CT", "round": 1, "avg_resources_before": 800}) == {"pistol": 1.0}


def test_round_plan_falls_back_to_overall(model):
    a = ref.round_plan(model, {"map": "de_nao_existe", "t_buy": "full"})
    assert a["plant_time_s"] == model["round_plan"]["overall"]["plant_time_s"]


def test_state_dict_is_not_mutated(model):
    s = _state()
    before = copy.deepcopy(s)
    ref.win_probability(model, s)
    assert s == before


# ---------- dinâmica das armas ----------

@pytest.fixture(scope="module")
def dyn():
    return json.loads((ARTIFACTS_DIR / "weapon_dynamics.json").read_text())


def test_recoil_scale_is_consistent_with_fit(dyn):
    s = dyn["recoil"]["scale"]
    assert s["ci95"][0] <= s["value"] <= s["ci95"][1]


def test_ak_pattern_rises_and_resets(dyn):
    assert wd.punch(dyn, "ak47", 1) == (0.0, 0.0)
    pitches = [wd.punch(dyn, "ak47", b)[0] for b in range(1, 9)]
    assert pitches == sorted(pitches, reverse=True) and pitches[-1] < -3.5        # a mira sobe
    cycle = dyn["recoil"]["patterns"]["ak47"]["cycle_time_s"]
    assert wd.next_bullet_index(dyn, "ak47", 7, cycle) == 8                        # contínuo
    assert wd.next_bullet_index(dyn, "ak47", 7, cycle * 1.5) == 1                  # pausa longa reinicia
    assert wd.next_bullet_index(dyn, "ak47", None, 0.0) == 1


def test_punch_holds_last_value_after_measured_range(dyn):
    top = dyn["recoil"]["patterns"]["ak47"]["max_measured_bullet"]
    assert wd.punch(dyn, "ak47", top + 10) == wd.punch(dyn, "ak47", top)


def test_bullet_direction_applies_scale(dyn):
    pitch, yaw = wd.bullet_direction(dyn, "ak47", 10.0, 20.0, 8)
    p_pitch, p_yaw = wd.punch(dyn, "ak47", 8)
    assert pitch == pytest.approx(10.0 + dyn["recoil"]["scale"]["value"] * p_pitch)
    assert yaw == pytest.approx(20.0 + dyn["recoil"]["scale"]["value"] * p_yaw)


# ---------- camada tática ----------

@pytest.fixture(scope="module")
def tactics():
    return json.loads((ARTIFACTS_DIR / "tactics.json").read_text())


@pytest.fixture(scope="module")
def playbook():
    return json.loads((ARTIFACTS_DIR / "tactics_playbook.json").read_text())


def test_forecast_and_occupancy_are_distributions(tactics):
    for m in tactics["maps"].values():
        for side in ("CT", "T"):
            for table in m["forecast"][side].values():
                for entry in table.values():
                    assert sum(entry["p"].values()) == pytest.approx(1.0, abs=5e-3)
            for bucket in m["occupancy"][side]["buckets"]:
                assert sum(bucket["p"].values()) == pytest.approx(1.0, abs=5e-3)


def test_zones_follow_the_sites(tactics):
    for m in tactics["maps"].values():
        places = m["places"]
        if "BombsiteA" in places:
            assert places["BombsiteA"]["zone"] == "A" and places["BombsiteB"]["zone"] == "B"
        for name, info in places.items():
            if info["kind"] == "spawn":
                assert info["zone"] == "Spawn"


def test_forecast_beats_plain_occupancy_on_unseen_matches(tactics):
    evaluated = [m["evaluation"] for m in tactics["maps"].values() if m["evaluation"]]
    assert len(evaluated) >= 5
    for ev in evaluated:
        assert ev["5s"]["improvement_pct"] > 30 and ev["10s"]["improvement_pct"] > 20


def test_playbook_is_consistent(tactics, playbook):
    ids = [r["id"] for m in playbook["maps"].values() for r in m["rounds"]]
    assert len(ids) == len(set(ids))
    for mp, m in playbook["maps"].items():
        assert len(m["rounds"]) == tactics["maps"][mp]["n_rounds"]
        for rnd in m["rounds"]:
            for side in ("CT", "T"):
                assert 1 <= len(rnd[side]) <= 5
                for player in rnd[side]:
                    for place, t_in, t_out in player["steps"]:
                        assert 0 <= place < len(m["places"]) and t_out > t_in >= 0


def test_place_at_respects_death(playbook):
    rnd = next(r for r in playbook["maps"]["de_mirage"]["rounds"] if any(p["died_at"] for p in r["T"]))
    i = next(i for i, p in enumerate(rnd["T"]) if p["died_at"])
    died = rnd["T"][i]["died_at"]
    assert tac.place_at(rnd, "T", i, died + 1.0) is None
    assert tac.place_at(rnd, "T", i, 0.0) is not None


def test_round_weights_prefer_same_buy_type(playbook):
    w = tac.round_weights(playbook, "de_mirage", "full")
    assert sum(x[1] for x in w) == pytest.approx(1.0)
    same = {r["id"] for r in playbook["maps"]["de_mirage"]["rounds"] if r["t_buy"] == "full"}
    assert {x[0] for x in w} == same


def test_tactic_metrics_on_example():
    t = load_tables([EXAMPLE])
    assert len(t["positions"]) > 0 and set(t["positions"]["side"]) <= {"CT", "T"}
    m = compute_metrics(t)
    assert "tactic.place_changes_per_player" in m and "tactic.dwell_s" in m
    assert any(k.startswith("tactic.zone_share.T.20s.") for k in m)
