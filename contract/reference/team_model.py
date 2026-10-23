"""Implementação de referência do team_model.json (só biblioteca padrão do Python).

É a definição executável do contrato: a versão em C# da Unity deve devolver os mesmos números
que estas funções para os mesmos estados (veja contract/test_vectors/team_model_vectors.json).

  win_probability(model, state)  -> chance do CT vencer o round naquele instante
  buy_distribution(model, state) -> probabilidades do tipo de compra do time
  round_plan(model, state)       -> plano de ataque do T (plant, bombsite, tempo)
"""
import math

FEATURE_NAMES = [
    "alive_diff", "alive_ct", "alive_t", "planted", "planted_x_alive_diff",
    "clock_unplanted", "clock_planted", "equip_log_ratio",
]


def clock_fraction(model, state):
    """Fração do relógio que resta: do timer do round (antes do plant) ou do timer da C4 (depois)."""
    c = model["win_probability"]["clock"]
    if state["bomb_planted"]:
        left = c["bomb_s"] - state["time_since_plant_s"]
        total = c["bomb_s"]
    else:
        left = c["round_s"] - state["round_time_s"]
        total = c["round_s"]
    return min(1.0, max(0.0, left / total))


def features(model, state):
    """Vetor de features do modelo de chance de vitória (ordem de FEATURE_NAMES)."""
    wp = model["win_probability"]
    planted = 1.0 if state["bomb_planted"] else 0.0
    diff = float(state["alive_ct"] - state["alive_t"])
    clock = clock_fraction(model, state)
    off = wp["equip_offset"]
    ratio = math.log((state["ct_equip_avg"] + off) / (state["t_equip_avg"] + off))
    return [diff, float(state["alive_ct"]), float(state["alive_t"]), planted, planted * diff,
            (1.0 - planted) * clock, planted * clock, ratio]


def sigmoid(x):
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def win_probability(model, state):
    """Chance do CT vencer o round.

    state: map, round_time_s, alive_ct, alive_t, bomb_planted, time_since_plant_s (se plantada),
           ct_equip_avg, t_equip_avg (valor médio de equipamento por jogador no fim do freeze time).
    """
    wp = model["win_probability"]
    if state["alive_ct"] <= 0:
        return 0.0
    if state["alive_t"] <= 0 and not state["bomb_planted"]:
        return 1.0
    x = wp["intercept"] + wp["map_intercepts"].get(state["map"], wp["unknown_map_intercept"])
    for name, value in zip(FEATURE_NAMES, features(model, state)):
        x += wp["coefficients"][name] * value
    return sigmoid(x)


def resources_bucket(model, avg_resources_before):
    edges = model["buy"]["resource_edges"]
    labels = model["buy"]["resource_labels"]
    for i in range(len(edges)):
        if avg_resources_before < edges[i]:
            return labels[i]
    return labels[-1]


def buy_distribution(model, state):
    """Probabilidade de cada tipo de compra do time.

    state: side ("CT"|"T"), round (número do round), avg_resources_before (média por jogador de
           dinheiro + valor do equipamento já carregado, antes da fase de compra).
    """
    if state["round"] in model["definitions"]["pistol_rounds"]:
        return {"pistol": 1.0}
    return dict(model["buy"]["type_distribution"][state["side"]][resources_bucket(model, state["avg_resources_before"])])


def round_plan(model, state):
    """Plano de ataque do T para o round: chance de plantar, bombsite e tempo do plant.

    state: map, t_buy (pistol|eco|force|full).
    """
    plans = model["round_plan"]["by_map"]
    p = plans.get(state["map"], model["round_plan"]["overall"])
    rate = p["plant_rate_by_t_buy"].get(state["t_buy"], p["plant_rate"])
    return {"plant_rate": rate, "site_a_share": p["site_a_share"], "plant_time_s": dict(p["plant_time_s"])}
