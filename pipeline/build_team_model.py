"""Treina a camada de time (contract/artifacts/team_model.json) e gera os vetores de teste.

Parte dos logs reais convertidos (data/<demo>/simlog.jsonl), o mesmo formato que a Unity grava:
  1. win_probability: chance do CT vencer o round a cada instante (regressão logística, validada por partida)
  2. buy: tipo de compra do time (eco/force/full) conforme o dinheiro, e o que cada jogador carrega
  3. round_plan: chance de plantar, bombsite e tempo do plant, por mapa

A implementação de referência está em contract/reference/team_model.py; os vetores de teste gerados aqui
em contract/test_vectors/ fixam o comportamento esperado para a versão em C#.

Uso: .venv/bin/python -m pipeline.build_team_model
"""
import json
import random
from datetime import date

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import GroupKFold

from calibration.metrics import KEY, round_frame, team_buys
from calibration.simlog import load_tables
from contract.reference import team_model as ref
from pipeline.common import (ARTIFACTS_DIR, BUY_ECO_MAX, BUY_FORCE_MAX, BUY_TYPES, CONTRACT_VERSION, DATA_DIR,
                             PISTOL_ROUNDS, VECTORS_DIR)

ROUND_S = 115.0        # duração do round, medida (game_rules.round_timing)
BOMB_S = 41.0          # timer da C4, medido (game_rules.bomb)
EQUIP_OFFSET = 500.0   # suaviza a razão de equipamento (evita dividir por valores pequenos)
C_GRID = [0.03, 0.1, 0.3, 1.0, 3.0]
RESOURCE_EDGES = [2500, 3500, 4500, 5500, 6500, 7500]
RESOURCE_LABELS = ["<2500", "2500-3500", "3500-4500", "4500-5500", "5500-6500", "6500-7500", "7500+"]
BUY_PRIOR_K = 5        # pseudo-contagens do prior (distribuição do lado) nas probabilidades de compra
PLAN_PRIOR_K = 10
MIN_MAP_PLANTS = 20
SEED = 7


# ---------- chance de vitória ----------

def win_states(t, stub):
    """Um estado por segundo de cada round: vivos, plant, relógio, equipamento e o resultado."""
    rf = round_frame(t)
    kills = t["kills"]
    kills = kills[~kills["after_round_end"]]
    deaths = {}
    for (match, rnd, side), g in kills.groupby(KEY + ["user_side"]):
        deaths[(match, rnd, side)] = np.sort(g["round_time"].to_numpy())
    equip = t["players"].groupby(KEY + ["side"])["equip_value"].mean().unstack("side")

    states, labels, groups = [], [], []
    for r in rf.itertuples():
        key = (r.match, r.round)
        ct_d, t_d = deaths.get((*key, "CT"), np.array([])), deaths.get((*key, "T"), np.array([]))
        eq = equip.loc[key]
        for sec in range(0, int(r.duration_s) + 1):
            planted = r.planted and r.plant_time_s <= sec
            states.append({
                "map": r.map, "round_time_s": float(sec),
                "alive_ct": 5 - int(np.searchsorted(ct_d, sec, side="right")),
                "alive_t": 5 - int(np.searchsorted(t_d, sec, side="right")),
                "bomb_planted": bool(planted),
                "time_since_plant_s": float(sec - r.plant_time_s) if planted else None,
                "ct_equip_avg": float(eq["CT"]), "t_equip_avg": float(eq["T"]),
            })
            labels.append(int(r.winner_side == "CT"))
            groups.append(r.match)
    return states, np.array(labels), np.array(groups)


def is_terminal(s):
    return s["alive_ct"] <= 0 or (s["alive_t"] <= 0 and not s["bomb_planted"])


def design_matrix(stub, states, maps):
    rows = []
    for s in states:
        f = ref.features(stub, s)
        rows.append(f + [1.0 if s["map"] == m else 0.0 for m in maps])
    return np.array(rows)


def lookup_baseline(train_states, y_train, test_states):
    """Baseline: taxa empírica por (vivos CT, vivos T, plantada), com Laplace."""
    from collections import defaultdict
    cnt = defaultdict(lambda: [1.0, 2.0])
    for s, y in zip(train_states, y_train):
        c = cnt[(s["alive_ct"], s["alive_t"], s["bomb_planted"])]
        c[0] += y
        c[1] += 1
    return np.array([cnt[(s["alive_ct"], s["alive_t"], s["bomb_planted"])][0] /
                     cnt[(s["alive_ct"], s["alive_t"], s["bomb_planted"])][1] for s in test_states])


def metrics_of(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return {"log_loss": round(float(log_loss(y, p)), 4), "brier": round(float(brier_score_loss(y, p)), 4),
            "auc": round(float(roc_auc_score(y, p)), 4)}


def train_win_probability(t):
    stub = {"win_probability": {"clock": {"round_s": ROUND_S, "bomb_s": BOMB_S}, "equip_offset": EQUIP_OFFSET}}
    states, y, groups = win_states(t, stub)
    keep = np.array([not is_terminal(s) for s in states])
    states = [s for s, k in zip(states, keep) if k]
    y, groups = y[keep], groups[keep]
    maps = sorted({s["map"] for s in states})
    X = design_matrix(stub, states, maps)

    folds = list(GroupKFold(n_splits=5).split(X, y, groups))
    best = None
    for c in C_GRID:
        oof = np.zeros(len(y))
        for tr, te in folds:
            oof[te] = LogisticRegression(C=c, max_iter=2000).fit(X[tr], y[tr]).predict_proba(X[te])[:, 1]
        ll = log_loss(y, np.clip(oof, 1e-6, 1 - 1e-6))
        if best is None or ll < best[0]:
            best = (ll, c, oof)
    _, c, oof = best

    base = np.zeros(len(y))
    for tr, te in folds:
        base[te] = lookup_baseline([states[i] for i in tr], y[tr], [states[i] for i in te])

    bins = np.linspace(0, 1, 11)
    idx = np.clip(np.digitize(oof, bins) - 1, 0, 9)
    calibration = [{"predicted": round(float(oof[idx == b].mean()), 3), "observed": round(float(y[idx == b].mean()), 3),
                    "n": int((idx == b).sum())} for b in range(10) if (idx == b).sum() >= 50]

    final = LogisticRegression(C=c, max_iter=2000).fit(X, y)
    n_feat = len(ref.FEATURE_NAMES)
    coef = final.coef_[0]
    return {
        "model": "logistic",
        "clock": {"round_s": ROUND_S, "bomb_s": BOMB_S},
        "equip_offset": EQUIP_OFFSET,
        "hard_rules": ["alive_ct == 0 -> 0.0", "alive_t == 0 and not bomb_planted -> 1.0"],
        "features": [
            {"name": "alive_diff", "definition": "alive_ct - alive_t"},
            {"name": "alive_ct", "definition": "alive_ct"},
            {"name": "alive_t", "definition": "alive_t"},
            {"name": "planted", "definition": "1 se a bomba foi plantada, senão 0"},
            {"name": "planted_x_alive_diff", "definition": "planted * alive_diff"},
            {"name": "clock_unplanted", "definition": "(1 - planted) * clock, com clock = clamp((round_s - round_time_s) / round_s, 0, 1)"},
            {"name": "clock_planted", "definition": "planted * clock, com clock = clamp((bomb_s - time_since_plant_s) / bomb_s, 0, 1)"},
            {"name": "equip_log_ratio", "definition": "ln((ct_equip_avg + equip_offset) / (t_equip_avg + equip_offset))"},
        ],
        "formula": "p_ct = sigmoid(intercept + map_intercepts[map] + sum(coefficients[f] * f))",
        "intercept": round(float(final.intercept_[0]), 8),
        "coefficients": {n: round(float(v), 8) for n, v in zip(ref.FEATURE_NAMES, coef[:n_feat])},
        "map_intercepts": {m: round(float(v), 8) for m, v in zip(maps, coef[n_feat:])},
        "unknown_map_intercept": 0.0,
        "evaluation": {
            "method": f"validação cruzada de 5 partes agrupada por partida, {len(y)} estados de {len(set(groups))} partidas; C={c}",
            "model": metrics_of(y, oof), "baseline_vivos_e_plant": metrics_of(y, base),
            "constant_50": metrics_of(y, np.full(len(y), 0.5)), "calibration": calibration,
        },
    }


# ---------- compra ----------

def smooth(counts, prior, k):
    total = sum(counts.values())
    return {key: round((counts[key] + k * prior[key]) / (total + k), 4) for key in counts}


def train_buy(t):
    p, buys = t["players"], team_buys(t)
    # Recursos = dinheiro + equipamento que o jogador já carrega (armas mantidas do round anterior)
    res = p.assign(res=p["money_before"] + p["equip_before"]).groupby(KEY + ["side"])["res"].mean().rename("avg_resources").reset_index()
    tb = buys.merge(res, on=KEY + ["side"])
    nonp = tb[~tb["round"].isin(PISTOL_ROUNDS)].copy()
    stub = {"buy": {"resource_edges": RESOURCE_EDGES, "resource_labels": RESOURCE_LABELS}}
    nonp["bucket"] = [ref.resources_bucket(stub, m) for m in nonp["avg_resources"]]
    types = [b for b in BUY_TYPES if b != "pistol"]
    dist, counts = {}, {}
    for side in ("CT", "T"):
        s = nonp[nonp["side"] == side]
        prior = {b: (s["buy"] == b).mean() for b in types}
        dist[side], counts[side] = {}, {}
        for label in RESOURCE_LABELS:
            g = s[s["bucket"] == label]
            dist[side][label] = smooth({b: int((g["buy"] == b).sum()) for b in types}, prior, BUY_PRIOR_K)
            counts[side][label] = int(len(g))

    # O que cada jogador carrega, por lado e tipo de compra
    pl = p.merge(buys[KEY + ["side", "buy"]], on=KEY + ["side"])
    loadouts = {}
    for (side, bt), g in pl.groupby(["side", "buy"]):
        prim = g["primary"].dropna()
        sec = g["secondary"].dropna()
        team_awp = g.assign(awp=(g["primary"] == "awp").astype(int)).groupby(KEY)["awp"].sum()
        loadouts.setdefault(side, {})[bt] = {
            "player_rounds": int(len(g)),
            "armor_rate": round(float((g["armor"] > 0).mean()), 4),
            "helmet_rate": round(float(g["helmet"].astype(bool).mean()), 4),
            "kit_rate": round(float(g["defuser"].astype(bool).mean()), 4) if side == "CT" else None,
            "primary_rate": round(float(len(prim) / len(g)), 4),
            "primary_share": {k: round(float(v), 4) for k, v in prim.value_counts(normalize=True).head(8).items()},
            "secondary_share": {k: round(float(v), 4) for k, v in sec.value_counts(normalize=True).head(5).items()},
            "awp_per_team": round(float(team_awp.mean()), 4),
            "grenades_per_player": {k: round(float(g[f"g_{k}"].mean()), 4) for k in ("smoke", "flash", "he", "molotov")},
            "equip_value": {f"p{q}": int(np.percentile(g["equip_value"], q)) for q in (10, 50, 90)},
        }
    return {
        "resource_edges": RESOURCE_EDGES, "resource_labels": RESOURCE_LABELS,
        "type_distribution": dist, "type_distribution_n": counts,
        "prior_strength": BUY_PRIOR_K,
        "note": "Recursos = média por jogador do time de (dinheiro + valor do equipamento já carregado) no início da fase de compra. Round de pistola (1 e 13): sempre 'pistol'.",
        "loadouts": loadouts,
    }


# ---------- plano de ataque do T ----------

def plan_of(sub, overall=None):
    n = len(sub)
    pl = sub[sub["planted"]]
    rate = float(sub["planted"].mean())
    a_prior = overall["site_a_share"] if overall else 0.5
    ab = pl["plant_site"].isin(["A", "B"]).sum()
    a_share = ((pl["plant_site"] == "A").sum() + PLAN_PRIOR_K * a_prior) / (ab + PLAN_PRIOR_K)
    by_buy = {}
    for bt in BUY_TYPES:
        g = sub[sub["t_buy"] == bt]
        if len(g):
            by_buy[bt] = round(float((g["planted"].sum() + PLAN_PRIOR_K * rate) / (len(g) + PLAN_PRIOR_K)), 4)
    src = pl if len(pl) >= MIN_MAP_PLANTS or overall is None else None
    q = (src if src is not None else None)
    times = {f"p{k}": round(float(np.percentile((q if q is not None else pl)["plant_time_s"], k)), 2) for k in (10, 25, 50, 75, 90)} \
        if (q is not None and len(q)) else dict(overall["plant_time_s"])
    return {"n_rounds": int(n), "plant_rate": round(rate, 4), "plant_rate_by_t_buy": by_buy,
            "site_a_share": round(float(a_share), 4), "plant_time_s": times}


def train_plan(t):
    rf = round_frame(t)
    overall = plan_of(rf)
    return {"overall": overall,
            "by_map": {m: plan_of(rf[rf["map"] == m], overall) for m in sorted(rf["map"].unique())},
            "note": "plant_rate_by_t_buy é suavizada em direção à taxa do mapa; site_a_share em direção à taxa geral."}


# ---------- vetores de teste ----------

def make_vectors(model, win_sample):
    rng = random.Random(SEED)
    maps = sorted(model["win_probability"]["map_intercepts"])
    wp = []
    # Grade: combinações de vivos x plant x tempo, com equipamento neutro e desigual
    for alive_ct in (1, 3, 5):
        for alive_t in (1, 3, 5):
            for planted in (False, True):
                for eq in ((4500.0, 4500.0), (6000.0, 1500.0)):
                    wp.append({"map": maps[(alive_ct + alive_t) % len(maps)], "round_time_s": float(20 + 15 * alive_ct),
                               "alive_ct": alive_ct, "alive_t": alive_t, "bomb_planted": planted,
                               "time_since_plant_s": 12.0 if planted else None, "ct_equip_avg": eq[0], "t_equip_avg": eq[1]})
    wp += [{"map": maps[0], "round_time_s": 30.0, "alive_ct": 0, "alive_t": 3, "bomb_planted": True, "time_since_plant_s": 5.0, "ct_equip_avg": 4000.0, "t_equip_avg": 4000.0},
           {"map": maps[0], "round_time_s": 30.0, "alive_ct": 2, "alive_t": 0, "bomb_planted": False, "time_since_plant_s": None, "ct_equip_avg": 4000.0, "t_equip_avg": 4000.0},
           {"map": "de_unknown", "round_time_s": 60.0, "alive_ct": 4, "alive_t": 4, "bomb_planted": False, "time_since_plant_s": None, "ct_equip_avg": 4000.0, "t_equip_avg": 4000.0}]
    wp += rng.sample(win_sample, 40)
    buy = []
    for side in ("CT", "T"):
        for rnd in (1, 2, 13, 5, 19):
            for res in (1000.0, 2000.0, 3000.0, 4000.0, 5000.0, 6000.0, 7000.0, 9000.0):
                buy.append({"side": side, "round": rnd, "avg_resources_before": res})
    plan = [{"map": m, "t_buy": b} for m in maps + ["de_unknown"] for b in BUY_TYPES]
    return {
        "contract_version": CONTRACT_VERSION, "generated_at": date.today().isoformat(), "tolerance": 1e-9,
        "description": "Estados de entrada e a saída esperada de contract/reference/team_model.py. A implementação em C# deve reproduzir 'expected' dentro de 'tolerance'.",
        "win_probability": [{"input": s, "expected": round(ref.win_probability(model, s), 12)} for s in wp],
        "buy_distribution": [{"input": s, "expected": ref.buy_distribution(model, s)} for s in buy],
        "round_plan": [{"input": s, "expected": ref.round_plan(model, s)} for s in plan],
    }


def main():
    files = sorted(DATA_DIR.glob("*/simlog.jsonl"))
    if not files:
        raise SystemExit("Sem logs reais. Rode: python -m pipeline.real_to_simlog")
    t = load_tables(files)
    print(f"{t['matches']} partidas, {len(t['rounds'])} rounds")

    wp = train_win_probability(t)
    ev = wp["evaluation"]
    print(f"win_probability  modelo {ev['model']} | baseline {ev['baseline_vivos_e_plant']} | 50% {ev['constant_50']['log_loss']}")
    model = {
        "schema_version": "1.0", "contract_version": CONTRACT_VERSION, "generated_at": date.today().isoformat(),
        "source": {"matches": t["matches"], "rounds": len(t["rounds"]), "maps": sorted(t["rounds"]["map"].unique().tolist())},
        "definitions": {"pistol_rounds": list(PISTOL_ROUNDS), "buy_types": BUY_TYPES,
                        "buy_type_rule": f"round em pistol_rounds -> 'pistol'; senão pelo valor médio de equipamento por jogador no fim do freeze time: < {BUY_ECO_MAX} 'eco', < {BUY_FORCE_MAX} 'force', senão 'full'",
                        "round_time_s": ROUND_S, "bomb_timer_s": BOMB_S},
        "win_probability": wp,
        "buy": train_buy(t),
        "round_plan": train_plan(t),
    }
    # Amostra de estados reais para os vetores de teste
    stub = {"win_probability": wp}
    states, _, _ = win_states(t, stub)
    sample = [s for s in states if not is_terminal(s)]

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    out = ARTIFACTS_DIR / "team_model.json"
    out.write_text(json.dumps(model, ensure_ascii=False, indent=1))
    VECTORS_DIR.mkdir(parents=True, exist_ok=True)
    vec = VECTORS_DIR / "team_model_vectors.json"
    vec.write_text(json.dumps(make_vectors(model, sample), ensure_ascii=False, indent=1))
    print(f"{out} ({out.stat().st_size // 1024} KB), {vec} ({vec.stat().st_size // 1024} KB)")
    for side in ("CT", "T"):
        print(f"compra {side}:", {k: v for k, v in list(model["buy"]["type_distribution"][side].items())[:7]})
    print("plano overall:", model["round_plan"]["overall"])


if __name__ == "__main__":
    main()
