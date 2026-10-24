"""Síntese de perfis de comportamento para jogadores que não existem nas demos (referência para o port em C#).

Parte do perfil medido de um jogador real da mesma função (o `template`) e o ajusta com quatro números, os `knobs`:

  gap         quantos pontos de `skill` o jogador está abaixo do template (negativo = acima); piora a mecânica
  aggression  -1 a 1: de passivo a agressivo (vem de `temperament`)
  utility     -1 a 1: de pouco a muito utilitário e troca de mortes (vem de `communication`)
  spread      -1 a 1: de regular a irregular (vem de `consistency`, invertido)

Os dados reais só têm jogadores de nível profissional. As inclinações abaixo são **hipóteses** sobre como a mecânica
piora com o nível; devem ser calibradas comparando o `kpr` e o `adr` da simulação com `performance` do perfil sintetizado.
Com todos os knobs em zero o perfil sai igual ao template.
"""
import copy
from typing import Dict, Optional

# Hipóteses de inclinação por ponto de `gap` (limites evitam valores impossíveis).
ACC_SLOPE, ACC_RANGE = 0.012, (0.35, 1.15)        # taxas de acerto e de headshot
ERR_SLOPE = 0.018                                 # erro angular da mira e do primeiro tiro
REACT_SLOPE = 0.010                               # tempo de reação
INSTANT_SLOPE, INSTANT_RANGE = 0.012, (0.3, 1.1)  # chance de atirar instantaneamente
LOST_TO_DELAYED = 0.7                             # parte do tiro instantâneo perdido que vira reação atrasada
STILL_SLOPE, STILL_RANGE = 0.006, (0.6, 1.1)      # chance de parar antes de atirar
KPR_SLOPE, ADR_SLOPE, DPR_SLOPE, KAST_SLOPE = 0.010, 0.008, 0.006, 0.004
GAP_RANGE = (-15.0, 60.0)
NEUTRAL_ATTRIBUTE, ATTRIBUTE_SCALE = 60.0, 40.0   # 60 = neutro; 20 e 100 saturam em -1 e 1
# Efeitos dos knobs de estilo.
FIRST_CONTACT_PER_AGGRESSION, OPENING_PER_AGGRESSION, SHOOT_PER_AGGRESSION = 0.25, 0.5, 0.08
UTILITY_EFFECT = 0.4
SPREAD_EFFECT, SPREAD_MIN = 0.35, 0.5
IGL_BIAS = {"aggression": -0.25, "utility": 0.3}

STYLE_OF_ROLE = {"awper": "awper", "entry": "entry", "lurker": "lurker", "support": "support",
                 "rifler": "rifler", "igl": "support", "coach": None}
PCTS = ("p10", "p25", "p50", "p75", "p90")
RATE_KEYS = ("value", "shrunk")


def style_for(role: str) -> Optional[str]:
    """Etiqueta (`role_tags`) do template a usar para a função; None se a função não joga partidas."""
    return STYLE_OF_ROLE.get(role, "rifler")


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _attr(hidden: Dict, key: str) -> float:
    return _clamp((hidden.get(key, NEUTRAL_ATTRIBUTE) - NEUTRAL_ATTRIBUTE) / ATTRIBUTE_SCALE, -1.0, 1.0)


def knobs_for(skill: float, hidden: Dict, role: str, template_skill: float) -> Dict:
    knobs = {"gap": _clamp(template_skill - skill, *GAP_RANGE),
             "aggression": _attr(hidden, "temperament"),
             "utility": _attr(hidden, "communication"),
             "spread": -_attr(hidden, "consistency")}
    if role == "igl":
        for k, bias in IGL_BIAS.items():
            knobs[k] = _clamp(knobs[k] + bias, -1.0, 1.0)
    return {k: round(v, 4) + 0.0 for k, v in knobs.items()}


def _r(x: float) -> float:
    return round(x, 6)


def _rate(d, mult=1.0, add=0.0, hi=1.0) -> None:
    if isinstance(d, dict):
        for k in RATE_KEYS:
            if d.get(k) is not None:
                d[k] = _r(_clamp(d[k] * mult + add, 0.0, hi))


def _dist(d, mult=1.0, widen=1.0) -> None:
    if not isinstance(d, dict) or "p50" not in d:
        return
    centre = d["p50"]
    for k in PCTS:
        if k in d:
            d[k] = _r((centre + (d[k] - centre) * widen) * mult)
    if "mean" in d:
        d["mean"] = _r(d["mean"] * mult)


def _num(d: dict, key: str, mult: float) -> None:
    if isinstance(d.get(key), (int, float)) and not isinstance(d.get(key), bool):
        d[key] = _r(d[key] * mult)


def synthesize_profile(template: Dict, knobs: Dict) -> Dict:
    p = copy.deepcopy(template)
    gap, aggression, utility = knobs["gap"], knobs["aggression"], knobs["utility"]
    widen = max(SPREAD_MIN, 1 + SPREAD_EFFECT * knobs["spread"])
    acc = _clamp(1 - ACC_SLOPE * gap, *ACC_RANGE)
    err = max(0.2, 1 + ERR_SLOPE * gap)
    react = max(0.3, 1 + REACT_SLOPE * gap)
    inst = _clamp(1 - INSTANT_SLOPE * gap, *INSTANT_RANGE)
    still = _clamp(1 - STILL_SLOPE * gap, *STILL_RANGE)
    mech, perf = p["mechanics"], p["performance"]

    for cls in mech.get("accuracy", {}).values():
        _rate(cls.get("overall"), acc)
        for group in ("by_distance", "by_spray_bullet"):
            for r in cls.get(group, {}).values():
                _rate(r, acc)

    _dist(mech.get("aim_error_first_bullet_deg"), err, widen)
    for d in mech.get("crosshair_placement", {}).values():
        _dist(d, err, widen)
    _dist(mech.get("reaction_time_s"), react, widen)

    eng = mech.get("engagement", {})
    _dist(eng.get("delayed_reaction_s"), react, widen)
    _rate(eng.get("fired_before_visible"), inst)
    for b in eng.get("by_aim_error", {}).values():
        for k in RATE_KEYS:
            i, dl, nn = b["instant"].get(k), b["delayed"].get(k), b["none"].get(k)
            if i is None or dl is None or nn is None:
                continue
            new_i = _clamp(i * inst, 0.0, 1.0)
            lost = i - new_i  # o que sai do tiro instantâneo vai para a reação atrasada e, em menor parte, para "sem tiro"
            new_d, new_n = dl + LOST_TO_DELAYED * lost, nn + (1 - LOST_TO_DELAYED) * lost
            if new_d < 0:
                new_d, new_n = 0.0, new_n + new_d
            if new_n < 0:
                new_d, new_n = new_d + new_n, 0.0
            b["instant"][k], b["delayed"][k], b["none"][k] = _r(new_i), _r(max(0.0, new_d)), _r(max(0.0, new_n))

    _rate(mech.get("movement", {}).get("still_shot_rate"), still)
    _rate(mech.get("shoots_after_sighting_rate"), 1.0, SHOOT_PER_AGGRESSION * aggression)

    _rate(perf.get("headshot_kill_rate"), acc)
    kpr, dpr = _clamp(1 - KPR_SLOPE * gap, 0.3, 1.3), 1 + DPR_SLOPE * gap
    _num(perf, "kpr", kpr)
    _num(perf, "dpr", dpr)
    _num(perf, "kd", kpr / dpr)
    _num(perf, "adr", _clamp(1 - ADR_SLOPE * gap, 0.4, 1.3))
    _num(perf, "kast", _clamp(1 - KAST_SLOPE * gap, 0.6, 1.1))

    _dist(perf.get("first_contact_s"), max(0.3, 1 - FIRST_CONTACT_PER_AGGRESSION * aggression), widen)
    _rate(perf.get("opening", {}).get("attempt_rate"), 1 + OPENING_PER_AGGRESSION * aggression)
    util = max(0.0, 1 + UTILITY_EFFECT * utility)
    for k in list(perf.get("utility", {})):
        if k.endswith("_per_round"):
            _num(perf["utility"], k, util)
    _num(perf, "trade_kills_per_round", util)
    _rate(perf.get("traded_death_rate"), util)

    p["synthetic"] = True
    return p
