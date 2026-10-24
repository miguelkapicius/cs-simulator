"""Modelos do modo manager: contrato, jogador, clube e oferta. Todos serializáveis em JSON."""
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

HIDDEN_KEYS = ("consistency", "communication", "ceiling", "lan_form", "temperament")


@dataclass
class Contract:
    salary_month: int
    signing_bonus: int
    end_week: int
    buyout: int

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "Contract":
        return cls(**d)


@dataclass
class Player:
    pid: str
    codename: str
    country: str
    role: str
    age: int
    tier: int
    skill: float
    hidden: Dict[str, float]
    hype: float
    form: float
    club_id: Optional[str]
    contract: Optional[Contract]
    profile_ref: Optional[str]

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["contract"] = self.contract.to_dict() if self.contract else None
        return d

    @classmethod
    def from_dict(cls, d: Dict) -> "Player":
        d = dict(d)
        d["contract"] = Contract.from_dict(d["contract"]) if d.get("contract") else None
        return cls(**d)


@dataclass
class Club:
    cid: str
    name: str
    tier: int
    budget: int
    prestige: float
    reputation: float
    roster: List[str] = field(default_factory=list)
    style: str = "conservative"
    is_human: bool = False
    points: int = 0

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "Club":
        return cls(**d)


@dataclass
class Offer:
    club_id: str
    salary_month: int
    signing_bonus: int
    weeks: int
    role: str

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "Offer":
        return cls(**d)
