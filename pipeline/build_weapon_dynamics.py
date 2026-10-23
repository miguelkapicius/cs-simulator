"""Mede nas demos como cada arma se comporta ao atirar (contract/artifacts/weapon_dynamics.json).

O que o game_rules.json traz dos arquivos do jogo são parâmetros; aqui está o comportamento, medido:
  recoil.patterns    punch da mira (graus) a cada bala de uma rajada, por arma (determinístico)
  recoil.scale       quanto do punch vira desvio real da bala (ajustado com os tiros que acertaram)
  recoil.reset       quando a rajada reinicia na bala 1 depois de uma pausa, e como o índice de recuo decai
  patterns[].penalty penalidade de precisão do jogo a cada bala (parte do cone de dispersão)
  penetration        quanto dano se perde nos tiros que atravessam parede/objeto (inferido do dano)

Uso: .venv/bin/python -m pipeline.build_weapon_dynamics
"""
import json
import sys
from datetime import date

import numpy as np
import pandas as pd
from demoparser2 import DemoParser

from pipeline.build_game_rules import DEFAULT_HG_MULT, measure_damage, predict_damage
from pipeline.build_player_profiles import extract_shots, load_demo_data
from contract.reference import weapon_dynamics as ref
from pipeline.common import ARTIFACTS_DIR, CONTRACT_VERSION, DATA_DIR, DEMOS_DIR, TICKRATE, VECTORS_DIR, weapon_class

PROPS = {
    "CCSPlayerPawn.CCSPlayer_AimPunchServices.m_predictableBaseAngle": "punch",
    "Weapon.m_fAccuracyPenalty": "penalty",
    "Weapon.m_flRecoilIndex": "recoil_index",
    "CCSPlayerPawn.m_iShotsFired": "shots_fired",
}
CONTINUITY = 1.3            # tiro contínuo: intervalo até 1,3 x o tempo de ciclo da arma
MIN_N_BULLET = 15           # amostras mínimas por bala para entrar na tabela
MAX_BULLET = 30
RESET_RATIOS = [(0, 1.2), (1.2, 1.5), (1.5, 2), (2, 3), (3, 5), (5, 10), (10, 1e9)]   # pausa / tempo de ciclo
DECAY_PAUSES = [(0.12, 0.2), (0.2, 0.3), (0.3, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 0.8), (0.8, 1.0), (1.0, 1.3)]   # segundos
MIN_N_BIN = 10
ATTENUATED_MARGIN = 1       # dano menor que o previsto em mais de 1 ponto = tiro que perdeu dano
FIT_MAX_DISTANCE_M = 30
FIT_MIN_BULLET = 3          # o ajuste da escala usa balas em que o recuo já importa
BOOTSTRAP = 300
SEED = 11


def game_weapons():
    rules = json.loads((ARTIFACTS_DIR / "game_rules.json").read_text())
    return rules["weapons"], rules["weapon_display_names"]


def collect_shots(demo, weapons):
    """Tiros de arma de fogo com o estado de recuo do atirador e o contexto da rajada."""
    stem = demo.stem
    match, rounds, kills, damages, grenades, ticks = load_demo_data(stem)
    parser = DemoParser(str(demo))
    shots = extract_shots(parser, rounds, damages)
    shots["wid"] = shots["weapon"].str.removeprefix("weapon_")
    shots = shots[shots["wid"].isin(weapons)].sort_values(["shooter", "tick"]).copy()

    st = parser.parse_ticks(list(PROPS), ticks=sorted(set(shots["tick"])))
    st["steamid"] = st["steamid"].astype(str)
    st = st.rename(columns=PROPS)
    st["p_pitch"] = st["punch"].map(lambda v: v[0])
    st["p_yaw"] = st["punch"].map(lambda v: v[1])
    shots = shots.merge(st[["tick", "steamid", "p_pitch", "p_yaw", "penalty", "recoil_index", "shots_fired"]],
                        left_on=["tick", "shooter"], right_on=["tick", "steamid"], how="left")

    # Contexto da rajada: intervalo até o tiro anterior/seguinte da mesma arma e mesmo round
    g = shots.groupby(["shooter", "round", "wid"])
    shots["gap_prev"] = g["tick"].diff()
    shots["gap_next"] = -g["tick"].diff(-1)
    shots["ri_prev"] = g["recoil_index"].shift()
    cycle = shots["wid"].map(lambda w: weapons[w]["cycle_time_s"]["normal"] * TICKRATE)
    shots["continuous"] = shots["gap_prev"].isna() | (shots["gap_prev"] <= CONTINUITY * cycle)
    shots["demo"] = stem
    return parser, shots


def collect_penetration(parser, rounds, weapons, names):
    """Danos de arma de fogo com a distância, o colete e o capacete do alvo (para comparar com a fórmula)."""
    return measure_damage(parser, rounds, weapons, names)


# ---------- agregação ----------

def fit_scale(df):
    """Inclinação (mira abaixo da cabeça) x (punch para cima), nos tiros que acertaram: a escala do recuo."""
    h = df[df["hit"] & (df["distance_m"] < FIT_MAX_DISTANCE_M) & (df["shots_fired"] >= FIT_MIN_BULLET) & df["p_pitch"].notna()]
    x, y = (-h["p_pitch"]).to_numpy(), h["aim_err_v_deg"].to_numpy()
    if len(h) < 100:
        return None
    slope = lambda xs, ys: float(np.polyfit(xs, ys, 1)[0])
    rng = np.random.default_rng(SEED)
    boots = [slope(x[i], y[i]) for i in (rng.integers(0, len(x), len(x)) for _ in range(BOOTSTRAP))]
    return {"fitted": round(slope(x, y), 3), "ci95": [round(float(np.percentile(boots, 2.5)), 3), round(float(np.percentile(boots, 97.5)), 3)],
            "n_hits": int(len(h)),
            "method": "regressão de (erro vertical da mira em relação à cabeça) sobre (punch para cima), tiros que acertaram a até 30 m, bala >= 3"}


def pattern_table(df, weapons):
    out = {}
    for wid, g in df.groupby("wid"):
        cont = g[g["continuous"] & g["shots_fired"].between(1, MAX_BULLET) & g["p_pitch"].notna()]
        rows = []
        for k, gk in cont.groupby("shots_fired"):
            if len(gk) < MIN_N_BULLET:
                break
            rows.append({"bullet": int(k), "n": int(len(gk)), "pitch": round(float(gk["p_pitch"].median()), 4),
                         "yaw": round(float(gk["p_yaw"].median()), 4),
                         "pitch_sd": round(float(gk["p_pitch"].std()), 3), "yaw_sd": round(float(gk["p_yaw"].std()), 3),
                         "penalty": round(float(gk["penalty"].median()), 5)})
        if len(rows) >= 3:
            out[wid] = {"cycle_time_s": weapons[wid]["cycle_time_s"]["normal"], "max_measured_bullet": rows[-1]["bullet"],
                        "bullets": rows}
    return out


def reset_table(df, weapons):
    """Chance da rajada reiniciar na bala 1 conforme a pausa (em ciclos da arma), por classe de arma automática."""
    out = {}
    df = df[df["gap_prev"].notna() & df["wid"].map(lambda w: weapons[w]["full_auto"])].copy()
    df["wclass"] = df["wid"].map(weapon_class)
    df["ratio"] = df["gap_prev"] / (df["wid"].map(lambda w: weapons[w]["cycle_time_s"]["normal"]) * TICKRATE)
    for wc, g in df.groupby("wclass"):
        rows = []
        for lo, hi in RESET_RATIOS:
            gb = g[(g["ratio"] > lo) & (g["ratio"] <= hi)]
            if len(gb) >= MIN_N_BIN:
                rows.append({"pause_over_cycle": [lo, None if hi > 1e8 else hi], "restart_at_bullet_1": round(float((gb["shots_fired"] == 1).mean()), 3), "n": int(len(gb))})
        # fração do índice de recuo (contínuo) que ainda resta depois da pausa
        d = g[(g["ratio"] > RESET_RATIOS[1][0]) & (g["ri_prev"] >= 3)].copy()
        d["pause_s"] = d["gap_prev"] / TICKRATE
        d["left"] = ((d["recoil_index"] - 1.0) / d["ri_prev"]).clip(0, 1)
        decay = [{"pause_s": [lo, hi], "fraction_left": round(float(gd["left"].median()), 3), "n": int(len(gd))}
                 for lo, hi in DECAY_PAUSES for gd in [d[(d["pause_s"] > lo) & (d["pause_s"] <= hi)]] if len(gd) >= MIN_N_BIN]
        if rows:
            out[wc] = {"restart_by_pause": rows, "recoil_index_decay": decay}
    return out


def penetration_table(hurt, weapons, kills):
    """Tiros que perdem dano (atravessaram parede/objeto/jogador), inferidos comparando o dano com a fórmula.

    O evento de dano não marca penetração; o kill marca (`penetrated`). Aqui um acerto é 'atenuado' se o dano na vida
    ficou mais de 1 ponto abaixo do previsto sem penetração, com o mesmo cálculo validado em game_rules.damage_model.
    """
    h = hurt[hurt["weapon"].map(lambda w: weapons[w].get("bullets_per_shot", 1) == 1)].copy()
    h = h[h["health"] > 0]                                   # dano letal é limitado à vida restante
    h["wclass"] = h["weapon"].map(weapon_class)

    def predicted(r):
        w = weapons[r["weapon"]]
        mult = w["headshot_multiplier"] if r["hitgroup"] == "head" else DEFAULT_HG_MULT.get(r["hitgroup"], 1.0)
        armored = False if r["hitgroup"] in ("left_leg", "right_leg") else (r["helmet"] if r["hitgroup"] == "head" else True)
        return predict_damage(w["damage"], w["range_modifier"], r["dist_units"], mult, w["armor_penetration"], r["armor_before"], armored)[0]

    h["pred"] = h.apply(predicted, axis=1)
    h["attenuated"] = h["dmg_health"] < h["pred"] - ATTENUATED_MARGIN
    h["frac"] = h["dmg_health"] / h["pred"].clip(lower=1)
    res = {"attenuated_hit_share": {}, "damage_fraction_when_attenuated": {}}
    for wc, g in h.groupby("wclass"):
        res["attenuated_hit_share"][wc] = {"value": round(float(g["attenuated"].mean()), 4), "n": int(len(g))}
        a = g[g["attenuated"]]
        if len(a) >= 30:
            res["damage_fraction_when_attenuated"][wc] = {"n": int(len(a)), **{f"p{q}": round(float(np.percentile(a["frac"], q)), 3) for q in (10, 25, 50, 75, 90)}}
    k = kills.copy()
    k["wclass"] = k["weapon"].map(weapon_class)
    res["kills_through_surfaces"] = {wc: {"value": round(float((g["penetrated"] > 0).mean()), 4), "n": int(len(g))}
                                     for wc, g in k[k["wclass"].notna()].groupby("wclass")}
    res["note"] = ("Tiros 'atenuados' são inferidos (dano abaixo do previsto); incluem atravessar paredes, objetos e jogadores. "
                   "A parcela atenuada é calculada só entre acertos que NÃO mataram (o dano letal é limitado à vida restante), "
                   "por isso é alta em armas fortes como a AWP. Dano de fogo e de granada não entra (hitgroup 'generic').")
    return res


def make_vectors(model):
    """Entradas e saídas esperadas de contract/reference/weapon_dynamics.py, para a versão em C#."""
    cases = {"next_bullet_index": [], "punch": [], "bullet_direction": [], "accuracy_penalty": []}
    for weapon, pat in model["recoil"]["patterns"].items():
        cycle, top = pat["cycle_time_s"], pat["max_measured_bullet"]
        for prev, pause in ((None, 5.0), (1, cycle), (4, cycle * 1.05), (4, cycle * 1.29), (4, cycle * 1.31), (12, 0.4), (top, cycle)):
            i = {"weapon": weapon, "prev_index": prev, "pause_s": round(pause, 6)}
            cases["next_bullet_index"].append({"input": i, "expected": ref.next_bullet_index(model, weapon, prev, pause)})
        for bullet in (1, 2, 5, top, top + 5):
            cases["punch"].append({"input": {"weapon": weapon, "bullet": bullet}, "expected": list(ref.punch(model, weapon, bullet))})
            cases["accuracy_penalty"].append({"input": {"weapon": weapon, "bullet": bullet}, "expected": ref.accuracy_penalty(model, weapon, bullet)})
            cases["bullet_direction"].append({"input": {"weapon": weapon, "eye_pitch": 3.5, "eye_yaw": -40.0, "bullet": bullet},
                                              "expected": [round(v, 9) for v in ref.bullet_direction(model, weapon, 3.5, -40.0, bullet)]})
    return {"contract_version": CONTRACT_VERSION, "generated_at": date.today().isoformat(), "tolerance": 1e-9,
            "description": "Entradas e saída esperada de contract/reference/weapon_dynamics.py. A versão em C# deve reproduzir 'expected' dentro de 'tolerance'.",
            **cases}


def main():
    weapons, names = game_weapons()
    demos = [d for d in sorted(DEMOS_DIR.glob("*.dem")) if (DATA_DIR / d.stem / "match.json").exists()]
    all_shots, all_hurt = [], []
    for demo in demos:
        rounds = json.loads((DATA_DIR / demo.stem / "rounds.json").read_text())
        parser, shots = collect_shots(demo, weapons)
        all_shots.append(shots)
        all_hurt.append(collect_penetration(parser, rounds, weapons, names))
        print(f"{demo.stem.split('__')[-1]}: {len(shots)} tiros", file=sys.stderr)
    shots = pd.concat(all_shots, ignore_index=True)
    hurt = pd.concat(all_hurt, ignore_index=True)

    patterns = pattern_table(shots, weapons)
    scale = fit_scale(shots[shots["wid"].isin(patterns)])
    kills = pd.concat([pd.read_parquet(DATA_DIR / d.stem / "kills.parquet") for d in demos], ignore_index=True)
    kills = kills[~kills["after_round_end"] & kills["attacker_steamid"].notna()]
    kills["wclass"] = kills["weapon"].map(weapon_class)
    pen = penetration_table(hurt, weapons, kills)

    doc = {
        "schema_version": "1.0", "contract_version": CONTRACT_VERSION, "generated_at": date.today().isoformat(),
        "source": {"matches": len(demos), "shots": int(len(shots)), "hits_used_for_scale": scale["n_hits"] if scale else 0},
        "recoil": {
            "conventions": [
                "pitch e yaw do punch em graus; pitch negativo = a mira sobe (padrão do jogo)",
                "'bullet' é a posição da bala na rajada: 1 = primeira depois de soltar o gatilho (igual ao spray_index do log)",
                "o punch é o valor do jogo (m_predictableBaseAngle) lido no instante do tiro, acumulado desde o início da rajada",
                "direção real da bala = ângulo da mira do jogador + scale.value * punch + dispersão (spread + inaccuracy)",
                "só rajadas contínuas (intervalo entre tiros até 1,3x o tempo de ciclo) entram nas tabelas",
                "depois de uma pausa maior que ~1,3 ciclo a rajada reinicia na bala 1 (ver reset.restart_by_pause)",
                "patterns[].penalty é o m_fAccuracyPenalty do jogo no instante do tiro: a parte do cone de dispersão que cresce com a rajada",
            ],
            "reset_rule": {"pause_over_cycle_max": CONTINUITY,
                           "meaning": "se a pausa desde o último tiro passar de pause_over_cycle_max x cycle_time_s, o próximo tiro é a bala 1"},
            "scale": {"value": 2.0, **(scale or {}),
                      "note": "O valor 2.0 é o weapon_recoil_scale padrão do CS; o ajuste fica dentro do intervalo de confiança."},
            "patterns": patterns,
            "reset": reset_table(shots, weapons),
        },
        "penetration": pen,
    }
    out = ARTIFACTS_DIR / "weapon_dynamics.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    VECTORS_DIR.mkdir(parents=True, exist_ok=True)
    (VECTORS_DIR / "weapon_dynamics_vectors.json").write_text(json.dumps(make_vectors(doc), ensure_ascii=False, indent=1))
    print(f"{out} ({out.stat().st_size // 1024} KB)")
    print("escala:", scale)
    print("armas com padrão:", {w: p["max_measured_bullet"] for w, p in patterns.items()})
    print("reinício:", json.dumps({wc: v["restart_by_pause"] for wc, v in doc["recoil"]["reset"].items()})[:700])
    print("penetração:", json.dumps({k: v for k, v in pen.items() if k != "note"})[:1100])


if __name__ == "__main__":
    main()
