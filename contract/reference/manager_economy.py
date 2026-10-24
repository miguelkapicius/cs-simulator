"""Economia do modo manager: fórmulas puras (referência para o port em C#).

Só números e dicionários simples entram e saem; nenhum objeto do jogo. Todos os parâmetros vêm de `manager_params.json`
(o bloco `params`), passados como `prm`. A Unity porta estas funções e confere com `test_vectors/manager_economy_vectors.json`.

Convenções de port:
  - dinheiro é inteiro e `int(x)` trunca em direção a zero (em C#, `(long)x`);
  - o resto é `double`, sem arredondar; os vetores usam tolerância 1e-9;
  - o ruído do scouting vem direto do sha256, sem gerador de números aleatórios (ver `scout_noise`).
"""
import hashlib
import math
from typing import Dict, List, Tuple

WEEKS_PER_MONTH = 4  # 48 semanas de temporada / 12 meses
TOP_N = 5            # titulares que definem a força do time


def _frac(x: float, lo: float, hi: float) -> float:
    return max(0.0, min(1.0, (x - lo) / (hi - lo)))


def salary_for(tier: int, skill: float, hype: float, prm: Dict) -> int:
    """Salário mensal dentro da faixa do tier; no Tier 1 a faixa 'star' começa na `skill` mínima de `salary_skill_range.star`."""
    bands, rng = prm["salary_bands"][str(tier)], prm["salary_skill_range"]
    if tier == 1:
        key = "star" if skill >= rng["star"][0] else "regular"
        lo, hi = bands[key]
        skill_norm = _frac(skill, *rng[key])
    else:
        lo, hi = bands["all"]
        skill_norm = _frac(skill, *rng["low"])
    blend = prm["salary_blend"]
    x = blend["skill"] * skill_norm + blend["hype"] * _frac(hype, 0, 100)
    return int(lo + x * (hi - lo))


def buyout_for(salary_month: int, hype: float, end_week: int, week: int, interested: int, prm: Dict) -> int:
    """Salário anual x temporadas que restam (com teto) x (1 + hype/divisor) x inflação por clubes interessados."""
    weeks_left = max(0, end_week - week)
    inflation = 1 + prm["buyout"]["interest_step"] * max(0, interested - 1)
    seasons_left = min(weeks_left / prm["season_weeks"], prm["buyout"]["max_seasons"])
    return int(salary_month * 12 * seasons_left * (1 + hype / prm["buyout"]["hype_divisor"]) * inflation)


def decay_hype(hype: float, weeks: int, prm: Dict) -> float:
    return hype * 0.5 ** (weeks / prm["hype_half_life_weeks"])


def match_update(hype: float, form: float, rating: float, won: bool, major: bool, prm: Dict) -> Tuple[float, float]:
    """(hype, forma) depois de uma partida; o Major multiplica a variação de hype."""
    h = prm["hype_match"]
    form = (1 - h["form_blend"]) * form + h["form_blend"] * (rating - 1.0) * h["form_scale"]
    delta = (rating - 1.0) * h["per_rating_point"] + (h["win"] if won else h["loss"])
    if major:
        delta *= h["major_multiplier"]
    return max(0.0, min(100.0, hype + delta)), form


def weekly_wages(salaries_month: List[int]) -> int:
    return sum(salaries_month) // WEEKS_PER_MONTH


def weekly_revenue(tier: int, rank: int, prm: Dict) -> int:
    """Patrocínio fixo do tier, ajustado linearmente pelo ranking dentro do tier (1 = melhor)."""
    hi, lo = prm["rank_factor"]
    size = prm["tier_sizes"][str(tier)]
    pos = (min(max(rank, 1), size) - 1) / max(1, size - 1)
    return int(prm["sponsor_week"][str(tier)] * (hi + (lo - hi) * pos))


def sticker_payout(tier: int, hypes: List[float], prm: Dict) -> int:
    """Repasse de stickers de um Major: proporcional ao hype médio do elenco; só o Tier 1 recebe."""
    pool = prm["sticker_pool"][str(tier)]
    if not pool or not hypes:
        return 0
    return int(pool * (sum(hypes) / len(hypes)) / 100)


def can_afford(budget: int, weekly_wage_total: int, offer_salary_month: int, signing_bonus: int, prm: Dict) -> bool:
    """Depois do bônus, o caixa precisa cobrir `cash_reserve_weeks` semanas da folha já com o novo salário."""
    weekly = weekly_wage_total + offer_salary_month // WEEKS_PER_MONTH
    return budget - signing_bonus >= prm["cash_reserve_weeks"] * weekly


def team_strength(club_tier: int, roster: List[Dict], prm: Dict) -> float:
    """Média da `skill` dos 5 melhores (sem o coach), de 0 a 1; elenco vazio usa a média do tier."""
    if not roster:
        return prm["generator"]["skill_mean"][str(club_tier)] / 100
    top = sorted((r["skill"] for r in roster if r["role"] != "coach"), reverse=True)[:TOP_N]
    return (sum(top) / len(top)) / 100 if top else 0.0


def role_term(role: str, skill: float, roster: List[Dict], prm: Dict) -> float:
    """1 se há vaga na função; 0,5 se ele entraria como titular de uma função cheia; 0 se seria reserva."""
    same = [r for r in roster if r["role"] == role]
    if len(same) < prm["role_cap"].get(role, 1):
        return 1.0
    return 0.5 if any(skill > r["skill"] for r in same) else 0.0


def score_offer(player: Dict, offer_salary_month: int, club: Dict, roster: List[Dict], prm: Dict) -> float:
    """Nota de uma oferta para o jogador: dinheiro, força do time, prestígio, função e reputação do manager.

    player = {tier, skill, hype, role}; club = {tier, prestige, reputation}; roster = [{role, skill}, ...] (inclui o coach)."""
    w = prm["weights"]
    market = max(1, salary_for(player["tier"], player["skill"], player["hype"], prm))
    money = math.tanh(offer_salary_month / market)
    money_weight = w["money"] * max(0.0, prm["money_star_discount"] - player["skill"] / 100)  # estrela liga menos para dinheiro
    return (money_weight * money
            + w["team"] * team_strength(club["tier"], roster, prm)
            + w["prestige"] * club["prestige"] / 100
            + w["role"] * role_term(player["role"], player["skill"], roster, prm)
            + w["reputation"] * club["reputation"] / 100)


def accepts(score: float, prm: Dict) -> bool:
    return score > prm["accept_threshold"]


def scout_noise(world_seed: int, pid: str, level: int, key: str, width: float) -> float:
    """Ruído uniforme em [-width, width], fixo para (mundo, jogador, nível, atributo).

    u = primeiros 8 bytes (big-endian) de sha256("<seed>:<pid>:<level>:<key>") dividido por 2^64; ruído = (2u - 1) * width."""
    digest = hashlib.sha256(("%s:%s:%s:%s" % (world_seed, pid, level, key)).encode("utf-8")).digest()
    return (2 * (int.from_bytes(digest[:8], "big") / 2 ** 64) - 1) * width


def scout_numbers(skill: float, hidden: Dict, pid: str, level: int, world_seed: int, prm: Dict) -> Dict:
    """Estimativa de `skill` e os atributos escondidos que o nível revela, com ruído, limitados a [0, 100]."""
    sc = prm["scouting"]
    width = sc["noise"][str(level)]
    clamp = lambda x: max(0.0, min(100.0, x))
    out = {"skill_estimate": clamp(skill + scout_noise(world_seed, pid, level, "skill", width))}
    for key in sc["reveals"].get(str(level), []):
        out[key] = clamp(hidden[key] + scout_noise(world_seed, pid, level, key, width))
    return out
