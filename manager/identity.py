"""Identidade ficcional: codinomes e países inventados. Nenhum nome real chega ao produto."""
import json
import random
from functools import lru_cache
from typing import Set

from pipeline.common import ARTIFACTS_DIR

_HEAD = ["ka", "zo", "ri", "mu", "ta", "ve", "lo", "xi", "no", "sa", "bu", "de", "fa", "gi", "ha",
         "jo", "ku", "le", "mi", "pa", "qu", "ro", "su", "to", "vi", "wo", "ya", "ze", "bra", "cri"]
_TAIL = ["x", "ron", "lix", "mo", "tek", "ra", "zen", "do", "vik", "ni", "bo", "sh", "ko", "ly", "pe",
         "rus", "ta", "um", "vo", "xa", "zy", "dar", "fin", "gus", "hex", "jin", "kal", "lor", "mer", "nax"]
COUNTRIES = ["BR", "AR", "CL", "US", "CA", "DK", "SE", "FI", "PL", "UA", "RU", "KZ", "DE", "FR", "ES",
             "PT", "TR", "AU", "CN", "MN"]


@lru_cache(maxsize=1)
def _real_identifiers() -> frozenset:
    with open(ARTIFACTS_DIR / "player_profiles.json", encoding="utf-8") as f:
        data = json.load(f)
    return frozenset(p["name"].lower() for p in data["players"])


def make_codename(rng: random.Random, taken: Set[str]) -> str:
    """Codinome novo: nunca repete um já usado nem coincide com o nome de um jogador real."""
    while True:
        name = rng.choice(_HEAD) + rng.choice(_TAIL)
        if len(taken) > len(_HEAD) * len(_TAIL) // 2:
            name += str(rng.randrange(10, 100))
        if name.lower() not in taken and name.lower() not in _real_identifiers():
            taken.add(name.lower())
            return name


def make_country(rng: random.Random) -> str:
    return rng.choice(COUNTRIES)
