"""Testes do gerador de jogadores por tier."""
import random

from manager.generate import generate_player


def sample(tier, n=600):
    rng, taken = random.Random(5), set()
    return [generate_player(rng, tier, taken) for _ in range(n)]


def test_mean_skill_falls_with_tier():
    m = [sum(p.skill for p in sample(t)) / 600 for t in (1, 2, 3)]
    assert m[0] > m[1] > m[2]


def test_low_tier_has_a_hidden_talent_tail():
    young = [p for p in sample(3) if p.hidden["ceiling"] >= 85 and p.age <= 20]
    assert 0.02 * 600 <= len(young) <= 0.09 * 600


def test_roles_cover_the_roster_needs():
    assert {p.role for p in sample(2)} >= {"awper", "igl", "rifler", "coach"}


def test_codenames_unique_in_a_sample():
    assert len({p.codename for p in sample(1)}) == 600


def test_requested_role_is_respected():
    rng = random.Random(1)
    assert generate_player(rng, 2, set(), role="awper").role == "awper"


def test_generated_players_start_free_without_a_profile():
    p = generate_player(random.Random(1), 3, set())
    assert p.club_id is None and p.contract is None and p.profile_ref is None
    assert p.tier == 3 and 0 <= p.skill <= 100


def test_pids_are_unique_in_a_sample():
    ps = sample(2, 1500)
    assert len({p.pid for p in ps}) == 1500
