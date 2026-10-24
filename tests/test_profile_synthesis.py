"""Síntese de perfis de comportamento para jogadores gerados: estilo pela função, ajuste pelos atributos."""
import copy
import itertools
import json
import math

import pytest

from contract.reference import profile_synthesis as ps
from pipeline.common import ARTIFACTS_DIR

PCTS = ("p10", "p25", "p50", "p75", "p90")


@pytest.fixture(scope="module")
def templates():
    return json.load(open(ARTIFACTS_DIR / "elite_players.json", encoding="utf-8"))["players"]


@pytest.fixture(scope="module")
def tpl(templates):
    return next(p for p in templates if "entry" in p["profile"]["role_tags"])["profile"]


def get(o, path):
    for k in path.split("."):
        o = o[k]
    return o


def no_knobs(**kw):
    k = {"gap": 0.0, "aggression": 0.0, "utility": 0.0, "spread": 0.0}
    k.update(kw)
    return k


def leaves(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from leaves(v, path + "." + k)
    elif isinstance(o, float):
        yield path, o


def test_zero_knobs_keep_the_real_behavior(tpl):
    out = ps.synthesize_profile(tpl, no_knobs())
    assert out.pop("synthetic") is True
    assert out == tpl


def test_synthesis_does_not_mutate_the_template(tpl):
    before = copy.deepcopy(tpl)
    ps.synthesize_profile(tpl, no_knobs(gap=40, aggression=1, utility=-1, spread=1))
    assert tpl == before


def test_a_bigger_skill_gap_makes_every_mechanical_marker_worse(tpl):
    near, far = (ps.synthesize_profile(tpl, no_knobs(gap=g)) for g in (5.0, 35.0))
    assert get(far, "mechanics.accuracy.rifle.overall.shrunk") < get(near, "mechanics.accuracy.rifle.overall.shrunk")
    assert get(far, "mechanics.aim_error_first_bullet_deg.p50") > get(near, "mechanics.aim_error_first_bullet_deg.p50")
    assert get(far, "mechanics.crosshair_placement.total_deg.p50") > get(near, "mechanics.crosshair_placement.total_deg.p50")
    assert get(far, "mechanics.engagement.delayed_reaction_s.p50") > get(near, "mechanics.engagement.delayed_reaction_s.p50")
    inst = "mechanics.engagement.by_aim_error.tight_lt2.instant.shrunk"
    assert get(far, inst) < get(near, inst)
    assert get(far, "performance.kpr") < get(near, "performance.kpr")
    assert get(far, "performance.dpr") > get(near, "performance.dpr")


def test_lost_instant_shots_become_delayed_reactions_and_each_bin_still_sums_to_one(tpl):
    out = ps.synthesize_profile(tpl, no_knobs(gap=40))
    for name, b in get(out, "mechanics.engagement.by_aim_error").items():
        for key in ("value", "shrunk"):
            assert math.isclose(b["instant"][key] + b["delayed"][key] + b["none"][key], 1.0, abs_tol=2e-3), name
    base = get(tpl, "mechanics.engagement.by_aim_error.tight_lt2")
    assert get(out, "mechanics.engagement.by_aim_error.tight_lt2.delayed.shrunk") > base["delayed"]["shrunk"]


def test_aggression_brings_the_first_contact_earlier_and_raises_opening_attempts(tpl):
    calm, bold = (ps.synthesize_profile(tpl, no_knobs(aggression=a)) for a in (-1.0, 1.0))
    assert get(bold, "performance.first_contact_s.p50") < get(calm, "performance.first_contact_s.p50")
    assert get(bold, "performance.opening.attempt_rate.shrunk") > get(calm, "performance.opening.attempt_rate.shrunk")
    assert get(bold, "mechanics.shoots_after_sighting_rate.shrunk") > get(calm, "mechanics.shoots_after_sighting_rate.shrunk")


def test_utility_knob_changes_grenades_and_trades(tpl):
    quiet, talker = (ps.synthesize_profile(tpl, no_knobs(utility=u)) for u in (-1.0, 1.0))
    assert get(talker, "performance.utility.flash_per_round") > get(quiet, "performance.utility.flash_per_round")
    assert get(talker, "performance.trade_kills_per_round") >= get(quiet, "performance.trade_kills_per_round")


def test_spread_widens_distributions_without_moving_the_median(tpl):
    steady, erratic = (ps.synthesize_profile(tpl, no_knobs(spread=s)) for s in (-1.0, 1.0))
    path = "mechanics.aim_error_first_bullet_deg"
    assert get(erratic, path + ".p50") == get(steady, path + ".p50")
    assert (get(erratic, path + ".p90") - get(erratic, path + ".p10")) > (get(steady, path + ".p90") - get(steady, path + ".p10"))


def test_every_template_stays_valid_across_the_whole_knob_grid(templates):
    for t in templates:
        for gap, a, u, s in itertools.product((-15, 0, 30, 60), (-1, 1), (-1, 1), (-1, 1)):
            out = ps.synthesize_profile(t["profile"], no_knobs(gap=gap, aggression=a, utility=u, spread=s))
            assert set(out) == set(t["profile"]) | {"synthetic"}
            assert all(math.isfinite(v) for _, v in leaves(out))
            for path, v in leaves(out):
                if path.endswith((".value", ".shrunk")) and ".accuracy." in path:
                    assert 0.0 <= v <= 1.0, path
            for blk in ("mechanics.aim_error_first_bullet_deg", "mechanics.engagement.delayed_reaction_s",
                        "performance.first_contact_s", "mechanics.crosshair_placement.total_deg"):
                d = get(out, blk)
                vals = [d[k] for k in PCTS if k in d]
                assert vals == sorted(vals), blk
            assert 0.0 <= get(out, "mechanics.shoots_after_sighting_rate.shrunk") <= 1.0


def test_roles_map_to_a_template_style():
    assert ps.style_for("awper") == "awper" and ps.style_for("entry") == "entry"
    assert ps.style_for("lurker") == "lurker" and ps.style_for("support") == "support"
    assert ps.style_for("rifler") == "rifler" and ps.style_for("igl") == "support"
    assert ps.style_for("coach") is None


def test_attributes_become_knobs_around_a_neutral_point():
    hidden = {"temperament": 60, "communication": 60, "consistency": 60, "lan_form": 10, "ceiling": 99}
    k = ps.knobs_for(skill=70.0, hidden=hidden, role="entry", template_skill=80.0)
    assert k == {"gap": 10.0, "aggression": 0.0, "utility": 0.0, "spread": 0.0}
    hot = dict(hidden, temperament=100, communication=20, consistency=20)
    k = ps.knobs_for(skill=70.0, hidden=hot, role="entry", template_skill=80.0)
    assert k["aggression"] == 1.0 and k["utility"] == -1.0 and k["spread"] == 1.0
    assert ps.knobs_for(skill=5.0, hidden=hidden, role="entry", template_skill=98.0)["gap"] == 60.0
    assert ps.knobs_for(skill=99.0, hidden=hidden, role="entry", template_skill=70.0)["gap"] == -15.0


def test_igl_leans_toward_utility_and_away_from_aggression():
    hidden = {"temperament": 60, "communication": 60, "consistency": 60}
    k = ps.knobs_for(skill=70.0, hidden=hidden, role="igl", template_skill=70.0)
    assert k["utility"] > 0 > k["aggression"]


def test_validator_accepts_the_vectors_and_flags_a_tampered_one(tmp_path, monkeypatch):
    from pipeline import validate_contract
    from pipeline.common import VECTORS_DIR
    assert validate_contract.check_synthesis_vectors() == []
    vec = json.loads((VECTORS_DIR / "profile_synthesis_vectors.json").read_text())
    vec["cases"][2]["expected"]["performance.kpr"] += 0.5
    (tmp_path / "profile_synthesis_vectors.json").write_text(json.dumps(vec))
    monkeypatch.setattr(validate_contract, "VECTORS_DIR", tmp_path)
    problems = validate_contract.check_synthesis_vectors()
    assert len(problems) == 1 and "performance.kpr" in problems[0]
