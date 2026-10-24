"""Comportamento dos jogadores no mapa: perfis reais dos de elite, perfis sintetizados para os gerados."""
import json
import random
from functools import lru_cache
from typing import Dict, List, Optional

from contract.reference import profile_synthesis as synth
from manager.models import Player
from pipeline.common import ARTIFACTS_DIR

NEAREST_TEMPLATES = 3  # o template sai por sorteio entre os 3 jogadores reais mais próximos em `skill`


@lru_cache(maxsize=1)
def load_templates() -> List[Dict]:
    with open(ARTIFACTS_DIR / "elite_players.json", encoding="utf-8") as f:
        return json.load(f)["players"]


def assign_behavior(rng: random.Random, role: str, skill: float, hidden: Dict) -> Optional[Dict]:
    """Escolhe o template pela função e calcula os knobs pelos atributos; None se a função não joga partidas."""
    style = synth.style_for(role)
    if style is None:
        return None
    templates = load_templates()
    pool = [t for t in templates if style in t["profile"]["role_tags"]] or templates
    nearest = sorted(pool, key=lambda t: (abs(t["skill"] - skill), t["pid"]))[:NEAREST_TEMPLATES]
    template = rng.choice(nearest)
    return {"style": style, "template": template["pid"],
            "knobs": synth.knobs_for(skill, hidden, role, template["skill"])}


def profile_of(player: Player) -> Optional[Dict]:
    """Perfil de comportamento no formato de player_profiles.json; None para quem não joga partidas."""
    by_pid = {t["pid"]: t for t in load_templates()}
    if player.behavior:
        return synth.synthesize_profile(by_pid[player.behavior["template"]]["profile"], player.behavior["knobs"])
    if player.profile_ref is not None:
        return by_pid["e%02d" % int(player.profile_ref)]["profile"]
    return None
