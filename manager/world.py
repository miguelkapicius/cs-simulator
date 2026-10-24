"""Estado do mundo do manager: jogadores, clubes, semana e RNG. Serializável em JSON."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from manager.models import Club, Player


@dataclass
class Event:
    kind: str
    week: int
    data: Dict = field(default_factory=dict)


@dataclass
class World:
    seed: int
    week: int
    difficulty: str
    players: Dict[str, Player]
    clubs: Dict[str, Club]
    human_cid: str
    rng_state: Optional[list] = None  # random.getstate() em forma de lista JSON

    def taken_names(self) -> Set[str]:
        return {p.codename.lower() for p in self.players.values()}

    def to_dict(self) -> Dict:
        return {
            "seed": self.seed, "week": self.week, "difficulty": self.difficulty,
            "human_cid": self.human_cid, "rng_state": self.rng_state,
            "players": {pid: p.to_dict() for pid, p in sorted(self.players.items())},
            "clubs": {cid: c.to_dict() for cid, c in sorted(self.clubs.items())},
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "World":
        return cls(
            seed=d["seed"], week=d["week"], difficulty=d["difficulty"], human_cid=d["human_cid"],
            rng_state=d.get("rng_state"),
            players={pid: Player.from_dict(p) for pid, p in d["players"].items()},
            clubs={cid: Club.from_dict(c) for cid, c in d["clubs"].items()},
        )
