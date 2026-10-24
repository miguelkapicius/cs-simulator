"""Os 40 jogadores de comportamento real, com identidade trocada (codinome, país, idade)."""
import json
import random
from typing import List

from manager.identity import make_codename, make_country
from manager.models import HIDDEN_KEYS, Player
from pipeline.common import ARTIFACTS_DIR


def skill_from_profile(profile: dict, all_profiles: List[dict]) -> float:
    """Percentil do ADR entre os perfis, mapeado para 70 a 98."""
    adr = profile["performance"]["adr"]
    below = sum(1 for p in all_profiles if p["performance"]["adr"] < adr)
    return 70.0 + 28.0 * below / max(1, len(all_profiles) - 1)


def elite_players(seed: int) -> List[Player]:
    with open(ARTIFACTS_DIR / "player_profiles.json", encoding="utf-8") as f:
        profiles = json.load(f)["players"]
    rng = random.Random(seed)
    taken: set = set()
    players = []
    for i, prof in enumerate(profiles):
        skill = skill_from_profile(prof, profiles)
        role = "awper" if "awper" in prof["role_tags"] else "rifler"
        players.append(Player(
            pid="e%02d" % i,
            codename=make_codename(rng, taken),
            country=make_country(rng),
            role=role,
            age=rng.randint(18, 34),
            tier=1,
            skill=round(skill, 2),
            hidden={k: round(rng.uniform(60, 85), 2) for k in HIDDEN_KEYS},
            hype=round(skill * 0.6, 2),
            form=0.0,
            club_id=None,
            contract=None,
            profile_ref=str(i),
        ))
    return players
