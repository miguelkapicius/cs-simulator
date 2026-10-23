"""Gera perfis individuais de jogadores para a simulação (profiles/player_profiles.json).

Usa as demos (tiros, visão e mira em alta resolução) e os dados já extraídos em data/
(rounds, kills, danos, granadas, ticks). Rode extract_demos.py antes.

Uso: .venv/bin/python build_player_profiles.py
"""
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from demoparser2 import DemoParser

from extract_demos import DEMOS_DIR, OUT_DIR as DATA_DIR, SIDE, assign_round, parse_event

ROOT = Path(__file__).parent
PROFILES_DIR = ROOT / "profiles"
SCHEMA_VERSION = "1.0"

UNIT_TO_M = 0.0254          # 1 unidade Source ≈ 1 polegada
TICKRATE = 64
EYE_STAND, EYE_CROUCH = 64.0, 46.0   # altura dos olhos/cabeça acima da origem (unidades)
SPOT_SAMPLE = 2             # resolução da visão: a cada 2 ticks (~31 ms)
SPOT_MIN_GAP_S = 0.5        # o inimigo precisa ter ficado fora de vista por 0,5 s para contar como novo avistamento
REACTION_WINDOW_S = 2.0     # tiro em até 2 s após avistar conta como reação
AIMED_SHOT_DEG = 10.0       # tiro "no alvo" se a mira está a menos de 10° do inimigo mais próximo
DUEL_WINDOW_S = 3.0         # duelo resolvido se alguém morre em até 3 s após o avistamento
TRADE_WINDOW_S = 5.0
STILL_SPEED = 40.0          # unidades/s; abaixo disso o tiro é considerado parado (counter-strafe)
MIN_DIST_SAMPLES = 30       # abaixo disso a distribuição do jogador cai para a média geral
SHRINK_K = 20               # peso da média geral nas taxas (suavização bayesiana)
PERCENTILES = [10, 25, 50, 75, 90]
DIST_BANDS_M = [(0, 10), (10, 20), (20, 30), (30, 999)]
SPRAY_BUCKETS = [(1, 1), (2, 3), (4, 6), (7, 99)]

WEAPON_CLASS = {
    **dict.fromkeys(["ak47", "m4a1", "m4a1_silencer", "m4a4", "famas", "galilar", "aug", "sg556"], "rifle"),
    "awp": "awp",
    **dict.fromkeys(["ssg08", "scar20", "g3sg1"], "sniper_other"),
    **dict.fromkeys(["glock", "usp_silencer", "hkp2000", "p250", "fiveseven", "tec9", "cz75a",
                     "deagle", "revolver", "elite"], "pistol"),
    **dict.fromkeys(["mac10", "mp9", "mp7", "mp5sd", "ump45", "p90", "bizon"], "smg"),
    **dict.fromkeys(["nova", "xm1014", "mag7", "sawedoff", "m249", "negev"], "heavy"),
}
AUTOMATIC = {"rifle", "smg", "heavy"}
HITGROUPS = ["head", "chest", "stomach", "left_arm", "right_arm", "left_leg", "right_leg", "neck", "generic"]
UTILITY = ["smoke", "flash", "he", "molotov"]


def weapon_class(name):
    if not isinstance(name, str):
        return None
    name = name.removeprefix("weapon_")
    return WEAPON_CLASS.get(name)


# ---------- geometria ----------

def aim_errors(sx, sy, sz, pitch, yaw, tx, ty, tz):
    """Erro de mira do atirador em relação ao ponto alvo (graus).

    Retorna (total, horizontal, vertical). Vertical positivo = mira abaixo do alvo
    (no Source, pitch positivo olha para baixo).
    """
    dx, dy, dz = tx - sx, ty - sy, tz - sz
    t_yaw = np.degrees(np.arctan2(dy, dx))
    t_pitch = -np.degrees(np.arctan2(dz, np.hypot(dx, dy)))
    yaw_err = (yaw - t_yaw + 180) % 360 - 180
    pitch_err = pitch - t_pitch
    p, y = np.radians(pitch), np.radians(yaw)
    aim = np.stack([np.cos(p) * np.cos(y), np.cos(p) * np.sin(y), -np.sin(p)])
    to = np.stack([dx, dy, dz]) / np.maximum(np.sqrt(dx**2 + dy**2 + dz**2), 1e-6)
    total = np.degrees(np.arccos(np.clip((aim * to).sum(axis=0), -1, 1)))
    return total, yaw_err, pitch_err


def eye_z(z, ducking):
    return z + np.where(ducking.fillna(False).astype(bool), EYE_CROUCH, EYE_STAND)


def pair_geometry(df, a="s_", b="t_"):
    """Adiciona distância e erros de mira de `a` (atirador/observador) para a cabeça de `b`."""
    sz = eye_z(df[a + "Z"], df[a + "ducking"])
    tz = eye_z(df[b + "Z"], df[b + "ducking"])
    total, yaw_err, pitch_err = aim_errors(
        df[a + "X"].to_numpy(), df[a + "Y"].to_numpy(), sz.to_numpy(),
        df[a + "pitch"].to_numpy(), df[a + "yaw"].to_numpy(),
        df[b + "X"].to_numpy(), df[b + "Y"].to_numpy(), tz.to_numpy(),
    )
    df["aim_err_deg"] = total
    df["aim_err_h_deg"] = np.abs(yaw_err)
    df["aim_err_v_deg"] = pitch_err
    df["distance_m"] = np.sqrt((df[a + "X"] - df[b + "X"]) ** 2 + (df[a + "Y"] - df[b + "Y"]) ** 2
                               + (df[a + "Z"] - df[b + "Z"]) ** 2) * UNIT_TO_M
    return df


def state_pairs(states, left, right):
    """Junta, por tick, o estado do jogador `left` (steamid coluna) com o de `right`."""
    s = states.add_prefix("s_").rename(columns={"s_tick": "tick"})
    t = states.add_prefix("t_").rename(columns={"t_tick": "tick"})
    return left.merge(s, left_on=["tick", "shooter"], right_on=["tick", "s_steamid"]).merge(
        t, left_on=["tick", right], right_on=["tick", "t_steamid"])


# ---------- extração por demo ----------

STATE_PROPS = ["X", "Y", "Z", "pitch", "yaw", "team_name", "is_alive", "ducking",
               "is_airborne", "shots_fired", "active_weapon_name"]


def load_demo_data(stem):
    d = DATA_DIR / stem
    match = json.loads((d / "match.json").read_text())
    rounds = json.loads((d / "rounds.json").read_text())
    kills = pd.read_parquet(d / "kills.parquet")
    damages = pd.read_parquet(d / "damages.parquet")
    grenades = pd.read_parquet(d / "grenades.parquet")
    ticks = pd.read_parquet(d / "ticks.parquet")
    return match, rounds, kills, damages, grenades, ticks


def extract_shots(parser, rounds, damages):
    """Um registro por tiro de arma de fogo, com alvo provável, acerto, distância, mira e movimento."""
    wf = parse_event(parser, "weapon_fire")
    wf["wclass"] = wf["weapon"].map(weapon_class)
    wf = wf[wf["wclass"].notna()]
    wf = assign_round(wf, rounds, TICKRATE)
    wf = wf[~wf["after_round_end"]]
    wf = wf.rename(columns={"user_steamid": "shooter"})[["round", "round_time", "tick", "shooter", "weapon", "wclass"]]
    wf["shooter"] = wf["shooter"].astype(str)

    shot_ticks = sorted(set(wf["tick"]) | set(wf["tick"] - 1))
    states = parser.parse_ticks(STATE_PROPS, ticks=shot_ticks)
    states["steamid"] = states["steamid"].astype(str)
    states["side"] = states["team_name"].map(SIDE)
    states = states.drop(columns=["team_name", "name"])

    # Velocidade horizontal do atirador (posição no tick anterior)
    prev = states[["tick", "steamid", "X", "Y"]].copy()
    prev["tick"] += 1
    shooter_state = states.merge(prev, on=["tick", "steamid"], suffixes=("", "_prev"), how="left")
    shooter_state["speed"] = np.hypot(shooter_state["X"] - shooter_state["X_prev"],
                                      shooter_state["Y"] - shooter_state["Y_prev"]) * TICKRATE

    # Candidatos a alvo: inimigos vivos no tick anterior ao tiro (no tiro letal a vítima
    # já aparece morta no próprio tick)
    cand = wf.merge(shooter_state.add_prefix("s_").rename(columns={"s_tick": "tick"}),
                    left_on=["tick", "shooter"], right_on=["tick", "s_steamid"])
    targets = states.add_prefix("t_").rename(columns={"t_tick": "tick"})
    targets["tick"] += 1
    cand = cand.merge(targets, on="tick")
    cand = cand[(cand["t_side"] != cand["s_side"]) & cand["t_is_alive"].astype(bool)]
    cand = pair_geometry(cand)

    # Acerto: dano do atirador com arma de fogo no mesmo tick (ou no seguinte)
    dmg = damages[damages["weapon"].map(weapon_class).notna()][["tick", "attacker_steamid", "user_steamid", "hitgroup", "dmg_health"]]
    hits = pd.concat([dmg, dmg.assign(tick=dmg["tick"] - 1)]).drop_duplicates(["tick", "attacker_steamid", "user_steamid"])
    hits = hits.rename(columns={"attacker_steamid": "shooter", "user_steamid": "hit_victim"})
    hit_any = hits.drop_duplicates(["tick", "shooter"])

    # Alvo = inimigo atingido; sem acerto, o inimigo mais próximo da mira
    cand = cand.merge(hit_any[["tick", "shooter", "hit_victim"]], on=["tick", "shooter"], how="left")
    cand["is_hit_target"] = cand["t_steamid"] == cand["hit_victim"]
    cand = cand.sort_values(["is_hit_target", "aim_err_deg"], ascending=[False, True])
    shots = cand.drop_duplicates(["tick", "shooter", "weapon"]).copy()
    shots["hit"] = shots["hit_victim"].notna()
    shots["target"] = shots["t_steamid"]
    return shots[["round", "round_time", "tick", "shooter", "weapon", "wclass", "target", "hit",
                  "aim_err_deg", "aim_err_h_deg", "aim_err_v_deg", "distance_m",
                  "s_speed", "s_is_airborne", "s_ducking", "s_shots_fired"]].rename(columns={
                      "s_speed": "speed", "s_is_airborne": "airborne", "s_ducking": "ducking",
                      "s_shots_fired": "spray_index"})


def extract_sightings(parser, rounds, shots, kills):
    """Avistamentos: observador passa a ver um inimigo depois de ≥0,5 s sem vê-lo."""
    sample = []
    for r in rounds:
        sample.extend(range(r["freeze_end_tick"], r["end_tick"] + 1, SPOT_SAMPLE))
    st = parser.parse_ticks(["X", "Y", "Z", "pitch", "yaw", "team_name", "is_alive", "ducking",
                             "active_weapon_name", "approximate_spotted_by"], ticks=sample)
    st["steamid"] = st["steamid"].astype(str)
    st["side"] = st["team_name"].map(SIDE)
    alive = st[st["is_alive"].astype(bool)]

    seen = alive[["tick", "steamid", "approximate_spotted_by"]].explode("approximate_spotted_by")
    seen = seen.dropna(subset=["approximate_spotted_by"])
    seen = seen.rename(columns={"steamid": "target", "approximate_spotted_by": "observer"})
    seen["observer"] = seen["observer"].astype("int64").astype(str)
    seen = seen.sort_values(["observer", "target", "tick"])
    gap = seen.groupby(["observer", "target"])["tick"].diff()
    onsets = seen[gap.isna() | (gap > SPOT_MIN_GAP_S * TICKRATE)][["tick", "observer", "target"]]

    # Geometria no instante do avistamento (observador -> cabeça do alvo)
    s = alive.drop(columns=["approximate_spotted_by", "name", "team_name"]).add_prefix("s_").rename(columns={"s_tick": "tick"})
    t = alive.drop(columns=["approximate_spotted_by", "name", "team_name"]).add_prefix("t_").rename(columns={"t_tick": "tick"})
    sp = onsets.merge(s, left_on=["tick", "observer"], right_on=["tick", "s_steamid"]).merge(
        t, left_on=["tick", "target"], right_on=["tick", "t_steamid"])
    sp = sp[sp["s_side"] != sp["t_side"]]
    sp = pair_geometry(sp)

    # Ignora avistamentos com o observador já atirando (luta em andamento)
    sh = shots[["tick", "shooter", "target", "aim_err_deg", "hit"]].sort_values("tick")
    recent = pd.merge_asof(sp.sort_values("tick"), sh[["tick", "shooter"]].rename(columns={"tick": "last_shot"}),
                           left_on="tick", right_on="last_shot", left_by="observer", right_by="shooter",
                           direction="backward")
    sp = recent[recent["last_shot"].isna() | (recent["tick"] - recent["last_shot"] > SPOT_MIN_GAP_S * TICKRATE)].drop(columns=["shooter", "last_shot"])

    # Reação: primeiro tiro do observador mirando nesse alvo em até 2 s
    aimed = sh[sh["aim_err_deg"] < AIMED_SHOT_DEG].rename(columns={"tick": "shot_tick", "target": "shot_target"})
    m = sp[["tick", "observer", "target"]].merge(aimed, left_on=["observer", "target"], right_on=["shooter", "shot_target"])
    m = m[(m["shot_tick"] >= m["tick"]) & (m["shot_tick"] <= m["tick"] + REACTION_WINDOW_S * TICKRATE)]
    first = m.sort_values("shot_tick").drop_duplicates(["tick", "observer", "target"])
    first["reaction_s"] = (first["shot_tick"] - first["tick"]) / TICKRATE
    sp = sp.merge(first[["tick", "observer", "target", "reaction_s"]], on=["tick", "observer", "target"], how="left")

    # Resultado do duelo: quem matou quem em até 3 s
    k = kills[~kills["after_round_end"] & kills["attacker_steamid"].notna()][["tick", "attacker_steamid", "user_steamid"]]
    win = sp[["tick", "observer", "target"]].merge(k, left_on=["observer", "target"], right_on=["attacker_steamid", "user_steamid"], suffixes=("", "_k"))
    lose = sp[["tick", "observer", "target"]].merge(k, left_on=["target", "observer"], right_on=["attacker_steamid", "user_steamid"], suffixes=("", "_k"))
    window = DUEL_WINDOW_S * TICKRATE
    win = win[(win["tick_k"] >= win["tick"]) & (win["tick_k"] <= win["tick"] + window)].assign(outcome="win")
    lose = lose[(lose["tick_k"] >= lose["tick"]) & (lose["tick_k"] <= lose["tick"] + window)].assign(outcome="loss")
    res = pd.concat([win, lose]).sort_values("tick_k").drop_duplicates(["tick", "observer", "target"])
    sp = sp.merge(res[["tick", "observer", "target", "outcome"]], on=["tick", "observer", "target"], how="left")
    sp["outcome"] = sp["outcome"].fillna("none")
    return sp[["tick", "observer", "target", "s_side", "distance_m", "aim_err_deg", "aim_err_h_deg",
               "aim_err_v_deg", "reaction_s", "outcome", "s_active_weapon_name", "t_active_weapon_name"]].rename(
        columns={"s_side": "side", "s_active_weapon_name": "obs_weapon", "t_active_weapon_name": "target_weapon"})


# ---------- estatísticas por round (kills, trades, KAST, utilitários) ----------

def round_stats(match, rounds, kills, damages, grenades, ticks):
    players = {p["steamid"]: p for p in match["players"]}
    k = kills[~kills["after_round_end"]].copy()
    rows = []
    for r in rounds:
        rn = r["round"]
        rk = k[k["round"] == rn].sort_values("tick")
        rd = damages[(damages["round"] == rn) & ~damages["after_round_end"]]
        rg = grenades[grenades["round"] == rn]
        deaths = dict(zip(rk["user_steamid"], rk["tick"]))
        killers = dict(zip(rk["user_steamid"], rk["attacker_steamid"]))
        opening = rk[rk["attacker_steamid"].notna()].head(1)
        sides = ticks[ticks["round"] == rn].drop_duplicates("steamid").set_index("steamid")["side"].to_dict()
        for sid in players:
            side = sides.get(sid)
            if side is None:
                continue
            my_kills = rk[(rk["attacker_steamid"] == sid) & (rk["user_side"] != side)]
            # Trade kill: matou alguém que tinha acabado de matar um colega
            trade_kills = 0
            for _, kk in my_kills.iterrows():
                victim = kk["user_steamid"]
                mates_killed = rk[(rk["attacker_steamid"] == victim) & (rk["user_side"] == side)
                                  & (rk["tick"] < kk["tick"]) & (rk["tick"] >= kk["tick"] - TRADE_WINDOW_S * TICKRATE)]
                trade_kills += int(len(mates_killed) > 0)
            died = sid in deaths
            traded = False
            if died and isinstance(killers.get(sid), str):
                kt, killer = deaths[sid], killers[sid]
                traded = bool(((rk["user_steamid"] == killer) & (rk["tick"] > kt)
                               & (rk["tick"] <= kt + TRADE_WINDOW_S * TICKRATE)).any())
            assists = int(((rk["assister_steamid"] == sid) & (rk["user_side"] != side)).sum())
            dmg = rd[(rd["attacker_steamid"] == sid) & (rd["user_side"] != side)]
            util_dmg = dmg[dmg["weapon"].isin(["hegrenade", "inferno", "molotov", "incgrenade"])]
            thrown = rg[rg["user_steamid"] == sid]["grenade"].value_counts()
            first_contact = pd.concat([
                rk.loc[(rk["attacker_steamid"] == sid) | (rk["user_steamid"] == sid), "round_time"],
                rd.loc[(rd["attacker_steamid"] == sid) | (rd["user_steamid"] == sid), "round_time"],
            ]).min()
            rows.append({
                "map": match["map"], "round": rn, "steamid": sid, "side": side,
                "won": r["winner_side"] == side,
                "kills": len(my_kills), "deaths": int(died), "assists": assists,
                "flash_assists": int(((rk["assister_steamid"] == sid) & rk["assistedflash"]).sum()),
                "headshot_kills": int(my_kills["headshot"].sum()),
                "damage": int(np.minimum(dmg["dmg_health"], 100).sum()),
                "utility_damage": int(util_dmg["dmg_health"].sum()),
                "trade_kills": trade_kills, "traded_death": traded,
                "kast": bool(len(my_kills) or assists or not died or traded),
                "opening_attempt": bool(len(opening) and sid in (opening["attacker_steamid"].iloc[0], opening["user_steamid"].iloc[0])),
                "opening_win": bool(len(opening) and opening["attacker_steamid"].iloc[0] == sid),
                "first_contact_s": None if pd.isna(first_contact) else float(first_contact),
                **{f"thrown_{g}": int(thrown.get(g, 0)) for g in UTILITY},
            })
    return pd.DataFrame(rows)


def positions(ticks, match):
    """Callouts onde o jogador passa mais tempo, por lado, e onde está aos 20 s de round."""
    t = ticks[~ticks["after_round_end"] & ticks["is_alive"]]
    out = {}
    for (sid, side), g in t.groupby(["steamid", "side"]):
        share = g["last_place_name"].value_counts(normalize=True).head(5)
        setup = g[(g["round_time"] >= 19) & (g["round_time"] <= 21)].drop_duplicates("round")["last_place_name"].value_counts(normalize=True).head(3)
        out.setdefault(sid, {})[side] = {
            "time_share": {k: round(float(v), 3) for k, v in share.items()},
            "position_at_20s": {k: round(float(v), 3) for k, v in setup.items()},
        }
    return {match["map"]: out}


# ---------- agregação ----------

def pct(series):
    s = pd.Series(series).dropna()
    if s.empty:
        return None
    return {f"p{p}": round(float(np.percentile(s, p)), 3) for p in PERCENTILES} | {"mean": round(float(s.mean()), 3), "n": int(len(s))}


def rate(num, den, base=None):
    num, den = int(num), int(den)
    out = {"value": round(num / den, 4) if den else None, "n": den}
    if base is not None:
        out["shrunk"] = round((num + SHRINK_K * base) / (den + SHRINK_K), 4)
    return out


def dist_with_fallback(player_series, base_dist):
    d = pct(player_series)
    if d is None or d["n"] < MIN_DIST_SAMPLES:
        return {**(base_dist or {}), "source": "baseline", "player_n": 0 if d is None else d["n"]}
    return {**d, "source": "player"}


def band(m):
    for lo, hi in DIST_BANDS_M:
        if lo <= m < hi:
            return f"{lo}-{hi}m" if hi < 999 else f"{lo}m+"
    return None


def spray_bucket(i):
    for lo, hi in SPRAY_BUCKETS:
        if lo <= i <= hi:
            return f"{lo}" if lo == hi else (f"{lo}-{hi}" if hi < 99 else f"{lo}+")
    return None


def mechanics(shots, sightings, hitgroups, base=None):
    """Parâmetros mecânicos de um conjunto de tiros/avistamentos (um jogador ou todos)."""
    b = base or {}
    # Tiros em combate: mira a menos de 10° de um inimigo, ou que acertaram alguém
    aimed = shots[(shots["aim_err_deg"] < AIMED_SHOT_DEG) | shots["hit"]]
    out = {"shots_total": int(len(shots)), "shots_aimed": int(len(aimed))}

    acc = {}
    for wc, g in aimed.groupby("wclass"):
        acc[wc] = {"overall": rate(g["hit"].sum(), len(g), b.get("accuracy", {}).get(wc, {}).get("overall", {}).get("value"))}
        for bd, gb in g.groupby(g["distance_m"].map(band)):
            bv = b.get("accuracy", {}).get(wc, {}).get("by_distance", {}).get(bd, {}).get("value")
            acc[wc].setdefault("by_distance", {})[bd] = rate(gb["hit"].sum(), len(gb), bv)
        if wc in AUTOMATIC:
            for sb, gs in g.groupby(g["spray_index"].map(spray_bucket)):
                bv = b.get("accuracy", {}).get(wc, {}).get("by_spray_bullet", {}).get(sb, {}).get("value")
                acc[wc].setdefault("by_spray_bullet", {})[sb] = rate(gs["hit"].sum(), len(gs), bv)
    out["accuracy"] = acc

    # Distribuição de acertos no corpo, por classe de arma
    hg = {}
    for wc, g in hitgroups.groupby("wclass"):
        counts = g["hitgroup"].value_counts()
        hg[wc] = {"n": int(len(g)), **{h: round(float(counts.get(h, 0) / len(g)), 4) for h in HITGROUPS if counts.get(h, 0)}}
    out["hitgroups"] = hg

    first_bullets = aimed[aimed["spray_index"] <= 1]
    out["aim_error_first_bullet_deg"] = dist_with_fallback(first_bullets["aim_err_deg"], b.get("aim_error_first_bullet_deg"))

    out["movement"] = {
        "still_shot_rate": rate((aimed["speed"] < STILL_SPEED).sum(), aimed["speed"].notna().sum(),
                                b.get("movement", {}).get("still_shot_rate", {}).get("value")),
        "speed_at_shot": dist_with_fallback(aimed["speed"], b.get("movement", {}).get("speed_at_shot")),
        "crouch_shot_rate": rate(aimed["ducking"].fillna(False).astype(bool).sum(), len(aimed),
                                 b.get("movement", {}).get("crouch_shot_rate", {}).get("value")),
        "airborne_shot_rate": rate(aimed["airborne"].fillna(False).astype(bool).sum(), len(aimed)),
    }

    # Tamanho do spray (armas automáticas): maior spray_index antes de reiniciar
    auto = shots[shots["wclass"].isin(AUTOMATIC)].sort_values(["shooter", "tick"])
    new_burst = (auto["spray_index"] <= 1) | (auto.groupby("shooter")["spray_index"].diff() <= 0)
    burst_len = auto.groupby([auto["shooter"], new_burst.cumsum()])["spray_index"].max()
    out["burst_length"] = dist_with_fallback(burst_len, b.get("burst_length"))

    react = sightings["reaction_s"].dropna()
    out["reaction_time_s"] = dist_with_fallback(react, b.get("reaction_time_s"))
    out["crosshair_placement"] = {
        "total_deg": dist_with_fallback(sightings["aim_err_deg"], b.get("crosshair_placement", {}).get("total_deg")),
        "horizontal_deg": dist_with_fallback(sightings["aim_err_h_deg"], b.get("crosshair_placement", {}).get("horizontal_deg")),
        "vertical_deg": dist_with_fallback(sightings["aim_err_v_deg"], b.get("crosshair_placement", {}).get("vertical_deg")),
    }
    out["shoots_after_sighting_rate"] = rate(react.size, len(sightings), b.get("shoots_after_sighting_rate", {}).get("value"))

    resolved = sightings[sightings["outcome"] != "none"]
    base_duel = b.get("duels", {}).get("win_rate", {}).get("value")
    duels = {"win_rate": rate((resolved["outcome"] == "win").sum(), len(resolved), base_duel)}
    for bd, g in resolved.groupby(resolved["distance_m"].map(band)):
        bv = b.get("duels", {}).get("by_distance", {}).get(bd, {}).get("value")
        duels.setdefault("by_distance", {})[bd] = rate((g["outcome"] == "win").sum(), len(g), bv)
    out["duels"] = duels
    return out


def performance(rs, base=None):
    b = base or {}
    n = len(rs)
    sides = {}
    for side, g in rs.groupby("side"):
        sides[side] = {"rounds": len(g), "kpr": round(g["kills"].mean(), 3), "adr": round(g["damage"].mean(), 1),
                       "survival_rate": round(1 - g["deaths"].mean(), 3), "round_win_rate": round(g["won"].mean(), 3)}
    opening = rs[rs["opening_attempt"]]
    deaths = rs["deaths"].sum()
    kills = rs["kills"].sum()
    return {
        "rounds": n,
        "kpr": round(kills / n, 3), "dpr": round(deaths / n, 3), "apr": round(rs["assists"].sum() / n, 3),
        "adr": round(rs["damage"].sum() / n, 1),
        "kd": round(kills / max(deaths, 1), 3),
        "kast": round(rs["kast"].mean(), 3),
        "headshot_kill_rate": rate(rs["headshot_kills"].sum(), kills, b.get("headshot_kill_rate", {}).get("value")),
        "survival_rate": round(1 - deaths / n, 3),
        "opening": {
            "attempt_rate": rate(len(opening), n, b.get("opening", {}).get("attempt_rate", {}).get("value")),
            "win_rate": rate(opening["opening_win"].sum(), len(opening), b.get("opening", {}).get("win_rate", {}).get("value")),
        },
        "trade_kills_per_round": round(rs["trade_kills"].sum() / n, 3),
        "traded_death_rate": rate(rs["traded_death"].sum(), deaths),
        "first_contact_s": pct(rs["first_contact_s"]),
        "utility": {
            **{f"{g}_per_round": round(rs[f"thrown_{g}"].sum() / n, 3) for g in UTILITY},
            "flash_assists_per_round": round(rs["flash_assists"].sum() / n, 3),
            "utility_damage_per_round": round(rs["utility_damage"].sum() / n, 1),
        },
        "by_side": sides,
    }


def weapon_usage(shots, kills):
    share = shots["wclass"].value_counts(normalize=True)
    top = shots["weapon"].str.removeprefix("weapon_").value_counts(normalize=True).head(5)
    kill_share = kills["weapon"].map(weapon_class).value_counts(normalize=True)
    return {"shot_share_by_class": {k: round(float(v), 3) for k, v in share.items()},
            "kill_share_by_class": {k: round(float(v), 3) for k, v in kill_share.items()},
            "top_weapons_by_shots": {k: round(float(v), 3) for k, v in top.items()}}


def infer_role(perf, usage, base_perf):
    tags = []
    if usage["kill_share_by_class"].get("awp", 0) >= 0.3:
        tags.append("awper")
    t = perf["opening"]["attempt_rate"]["value"] or 0
    if t >= 1.25 * (base_perf["opening"]["attempt_rate"]["value"] or 0):
        tags.append("entry")
    if perf["utility"]["flash_per_round"] >= 1.25 * base_perf["utility"]["flash_per_round"]:
        tags.append("support")
    if perf["first_contact_s"] and perf["first_contact_s"]["p50"] > 1.2 * base_perf["first_contact_s"]["p50"]:
        tags.append("lurker")
    return tags or ["rifler"]


def main():
    PROFILES_DIR.mkdir(exist_ok=True)
    all_shots, all_sight, all_rounds, all_hg, all_kills = [], [], [], [], []
    pos, players, maps = {}, {}, []

    for demo in sorted(DEMOS_DIR.glob("*.dem")):
        stem = demo.stem
        match, rounds, kills, damages, grenades, ticks = load_demo_data(stem)
        parser = DemoParser(str(demo))
        shots = extract_shots(parser, rounds, damages)
        sight = extract_sightings(parser, rounds, shots, kills)
        rs = round_stats(match, rounds, kills, damages, grenades, ticks)
        hg = damages[~damages["after_round_end"] & (damages["user_side"] != damages["attacker_side"])].copy()
        hg["wclass"] = hg["weapon"].map(weapon_class)
        hg = hg[hg["wclass"].notna()][["attacker_steamid", "wclass", "hitgroup"]]
        for df in (shots, sight, rs, hg):
            df["map"] = match["map"]
        all_shots.append(shots); all_sight.append(sight); all_rounds.append(rs); all_hg.append(hg)
        all_kills.append(kills[~kills["after_round_end"] & (kills["attacker_side"] != kills["user_side"])])
        for sid, sides in positions(ticks, match)[match["map"]].items():
            pos.setdefault(sid, {})[match["map"]] = sides
        for p in match["players"]:
            players[p["steamid"]] = p
        maps.append({"map": match["map"], "demo": match["demo"], "rounds": match["rounds_played"], "final_score": match["final_score"]})
        print(f"{stem}: {len(shots)} tiros, {len(sight)} avistamentos, {sight['reaction_s'].notna().sum()} reações")

    shots = pd.concat(all_shots, ignore_index=True)
    sight = pd.concat(all_sight, ignore_index=True)
    rs = pd.concat(all_rounds, ignore_index=True)
    hg = pd.concat(all_hg, ignore_index=True)
    kills = pd.concat(all_kills, ignore_index=True)

    base_mech = mechanics(shots, sight, hg)
    base_perf = performance(rs)

    profiles = []
    for sid, p in sorted(players.items(), key=lambda kv: (kv[1]["team"], kv[1]["name"].lower())):
        ps, pp, pr = shots[shots["shooter"] == sid], sight[sight["observer"] == sid], rs[rs["steamid"] == sid]
        ph = hg[hg["attacker_steamid"] == sid]
        perf = performance(pr, base_perf)
        usage = weapon_usage(ps, kills[kills["attacker_steamid"] == sid])
        profiles.append({
            "steamid": sid, "name": p["name"], "team": p["team"],
            "role_tags": infer_role(perf, usage, base_perf),
            "mechanics": mechanics(ps, pp, ph, base_mech),
            "performance": perf,
            "weapons": usage,
            "positions": pos.get(sid, {}),
        })

    out = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": date.today().isoformat(),
        "source": {"matches": maps, "total_rounds": sum(m["rounds"] for m in maps),
                   "parser": "demoparser2", "tickrate": TICKRATE},
        "units": {"distance": "metros (1 unidade Source = 0,0254 m)", "angles": "graus", "time": "segundos",
                  "speed": "unidades Source/s (velocidade máx. com faca = 250)"},
        "method": {
            "aimed_shot_deg": AIMED_SHOT_DEG, "reaction_window_s": REACTION_WINDOW_S,
            "spot_min_gap_s": SPOT_MIN_GAP_S, "duel_window_s": DUEL_WINDOW_S, "trade_window_s": TRADE_WINDOW_S,
            "still_speed": STILL_SPEED, "min_distribution_samples": MIN_DIST_SAMPLES, "shrink_k": SHRINK_K,
            "eye_height_units": {"standing": EYE_STAND, "crouching": EYE_CROUCH},
        },
        "baseline": {"mechanics": base_mech, "performance": base_perf},
        "players": profiles,
    }
    path = PROFILES_DIR / "player_profiles.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    print(f"\n{path} ({path.stat().st_size // 1024} KB): {len(profiles)} jogadores")
    for pr in profiles:
        m, f = pr["mechanics"], pr["performance"]
        rt = m["reaction_time_s"]
        print(f"  {pr['team']:8} {pr['name']:10} {','.join(pr['role_tags']):16} KPR {f['kpr']:.2f} ADR {f['adr']:5.1f} "
              f"KAST {f['kast']:.2f} | reação p50 {rt.get('p50')}s ({rt['source']}) | duelo {m['duels']['win_rate']['value']}")


if __name__ == "__main__":
    main()
