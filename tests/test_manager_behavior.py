"""Jogadores gerados ganham estilo de jogo pela função e pelos atributos, no formato dos perfis reais."""
import json
import random
import statistics as st


from manager.behavior import assign_behavior, load_templates, profile_of
from manager.elite import elite_players
from manager.game import new_game
from manager.generate import generate_player
from manager.models import Player


def sample(role, tier=3, n=120, seed=7):
    rng, taken = random.Random(seed), set()
    return [generate_player(rng, tier, taken, role=role) for _ in range(n)]


def test_every_player_who_plays_has_a_behavior_and_the_coach_does_not():
    rng, taken = random.Random(1), set()
    for role in ("awper", "igl", "entry", "lurker", "support", "rifler"):
        p = generate_player(rng, 2, taken, role=role)
        assert set(p.behavior) == {"style", "template", "knobs"}
        assert set(p.behavior["knobs"]) == {"gap", "aggression", "utility", "spread"}
    assert generate_player(rng, 2, taken, role="coach").behavior is None


def test_the_template_is_a_real_player_with_the_style_of_the_role():
    by_pid = {t["pid"]: t for t in load_templates()}
    for role, tag in (("awper", "awper"), ("entry", "entry"), ("lurker", "lurker"), ("igl", "support")):
        for p in sample(role, n=15):
            assert tag in by_pid[p.behavior["template"]]["profile"]["role_tags"], (role, p.behavior)


def test_profile_of_returns_a_synthetic_profile_with_the_real_profile_layout():
    real = load_templates()[0]["profile"]
    p = sample("rifler", n=1)[0]
    prof = profile_of(p)
    assert prof["synthetic"] is True
    assert set(prof) == set(real) | {"synthetic"}
    assert set(prof["mechanics"]) == set(real["mechanics"])


def test_profile_of_the_elite_is_the_real_behavior_and_of_the_coach_is_none():
    elite = elite_players(1)[0]
    assert profile_of(elite) == next(t for t in load_templates() if t["pid"] == "e00")["profile"]
    assert profile_of(sample("coach", n=1)[0]) is None


def test_style_follows_the_function_in_the_numbers():
    med = lambda role, path: st.median(profile_of(p)["performance"][path[0]][path[1]] for p in sample(role))
    entry = med("entry", ("first_contact_s", "p50"))
    lurker = med("lurker", ("first_contact_s", "p50"))
    assert entry < lurker
    flash = lambda role: st.mean(profile_of(p)["performance"]["utility"]["flash_per_round"] for p in sample(role))
    assert flash("support") > flash("entry")


def test_lower_tiers_play_worse_than_higher_tiers():
    kpr = lambda tier: st.mean(profile_of(p)["performance"]["kpr"] for p in sample("rifler", tier=tier, n=150))
    err = lambda tier: st.mean(profile_of(p)["mechanics"]["aim_error_first_bullet_deg"]["p50"]
                               for p in sample("rifler", tier=tier, n=150))
    assert kpr(1) > kpr(2) > kpr(3)
    assert err(1) < err(2) < err(3)


def test_temperament_and_communication_move_the_profile():
    base = sample("rifler", n=1)[0]
    bold = Player(**{**base.__dict__, "hidden": dict(base.hidden, temperament=100, communication=100)})
    shy = Player(**{**base.__dict__, "hidden": dict(base.hidden, temperament=20, communication=20)})
    bold.behavior = assign_behavior(random.Random(3), "rifler", bold.skill, bold.hidden)
    shy.behavior = dict(bold.behavior, knobs=assign_behavior(random.Random(3), "rifler", shy.skill, shy.hidden)["knobs"])
    assert profile_of(bold)["performance"]["first_contact_s"]["p50"] < profile_of(shy)["performance"]["first_contact_s"]["p50"]


def test_behavior_survives_save_and_load():
    w = new_game(1, "normal", "Aurora")
    p = next(p for p in w.players.values() if p.behavior)
    again = Player.from_dict(json.loads(json.dumps(p.to_dict())))
    assert again.behavior == p.behavior and profile_of(again) == profile_of(p)


def test_every_non_coach_in_a_new_world_has_a_profile():
    w = new_game(2, "normal", "Aurora")
    for p in w.players.values():
        if p.role == "coach":
            assert profile_of(p) is None
        else:
            assert profile_of(p) is not None, p.pid
